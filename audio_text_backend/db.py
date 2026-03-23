import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine.base import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from audio_text_backend.config import Config
from audio_text_backend.errors import DBError

ROOT = Path(__file__).parents[1].resolve()
ALEMBIC_PATH = ROOT.joinpath("alembic")

logger = logging.getLogger(__name__)


_async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init() -> async_sessionmaker[AsyncSession]:
    """Initialise the async session factory (called once at application startup)."""
    global _async_session_factory
    logger.info("Initialising async database session")
    db = Config.database
    async_url = f"postgresql+asyncpg://{db.user}:{db.password}@{db.host}:{db.port}/{db.database}"
    engine = create_async_engine(async_url, echo=False)
    _async_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return _async_session_factory


async def run_migrations_async(skip: bool = False) -> None:
    """Run Alembic migrations via an async engine.

    Uses a PostgreSQL advisory lock (pg_advisory_lock) so that concurrent
    Cloud Run instances serialise migration execution — only the first instance
    to acquire the lock actually runs the migrations; the others wait and then
    confirm the schema is already up-to-date.
    """
    if skip:
        return

    from alembic.command import stamp as alembic_stamp
    from alembic.command import upgrade as alembic_upgrade
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    logger.info("Acquiring advisory lock and running async migrations")
    db = Config.database
    async_url = f"postgresql+asyncpg://{db.user}:{db.password}@{db.host}:{db.port}/{db.database}"
    engine = create_async_engine(async_url, echo=False)
    # Separate AUTOCOMMIT engine for the advisory lock so that a failed
    # migration transaction cannot prevent the unlock from executing.
    lock_engine = create_async_engine(async_url, echo=False, isolation_level="AUTOCOMMIT")

    async with lock_engine.connect() as lock_conn:
        await lock_conn.execute(text("SELECT pg_advisory_lock(7369143247)"))
        try:

            def _run(sync_conn: Connection) -> None:
                from .model import Base  # noqa: PLC0415

                Base.metadata.create_all(bind=sync_conn)
                cfg = AlembicConfig()
                cfg.attributes["connection"] = sync_conn
                cfg.set_section_option("alembic", "script_location", str(ALEMBIC_PATH))

                script = ScriptDirectory.from_config(cfg)
                context = MigrationContext.configure(sync_conn)
                head_rev = script.get_current_head()
                current_rev = context.get_current_revision()

                if current_rev is None:
                    # Schema was built directly by create_all (no alembic_version row).
                    # The schema already matches the latest models, so stamp to head
                    # to record this fact without re-running any migration scripts.
                    logger.info("No alembic revision found; stamping schema to head: %s", head_rev)
                    alembic_stamp(cfg, "head")
                elif current_rev != head_rev:
                    logger.info("Upgrading database from %s to %s", current_rev, head_rev)
                    alembic_upgrade(cfg, "head")
                else:
                    logger.info("Database is already at head: %s", head_rev)

            async with engine.begin() as conn:
                await conn.run_sync(_run)
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(7369143247)"))

    await lock_engine.dispose()
    await engine.dispose()
    logger.info("Async migrations complete")


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of async operations."""
    assert _async_session_factory is not None, "DB not initialized — call await db.init() first"
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Session rollback due to exception: {e}")
            raise DBError()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session.

    Wraps the session in an explicit transaction: commits automatically on
    successful return, rolls back on any exception (including non-SQLAlchemy
    exceptions such as HTTPException or business-logic errors).
    """
    assert _async_session_factory is not None, "DB not initialized — call await db.init() first"
    async with _async_session_factory() as session:
        async with session.begin():
            yield session
