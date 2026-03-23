from datetime import date
from typing import Any, Type, TypeVar, overload

from sqlalchemy import ARRAY, Date, MetaData, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped
from sqlalchemy.orm.decl_api import DeclarativeMeta

from audio_text_backend import db
from audio_text_backend.errors import Error, NoDataFound
from audio_text_backend.utils import to_list

T = TypeVar("T", bound="Base")

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    __errors__: dict[str, type[Error]] = {}
    metadata = MetaData(naming_convention=naming_convention)

    id: Mapped[str] | None

    # ------------------------------------------------------------------ find --

    @overload
    @classmethod
    async def find(
        cls: Type[T],
        filter_defs: dict[str, Any],
        joins: list[DeclarativeMeta],
        **filters: Any,
    ) -> list[T]: ...

    @overload
    @classmethod
    async def find(
        cls: Type[T],
        **filters: Any,
    ) -> list[T]: ...

    @classmethod
    async def find(
        cls: Type[T],
        filter_defs: dict[str, Any] | None = None,
        joins: list[DeclarativeMeta] | None = None,
        *,
        session: AsyncSession | None = None,
        **filters: Any,
    ) -> list[T]:
        async def _exec(s: AsyncSession) -> list[T]:
            stmt = select(cls)

            if joins:
                for jn in joins:
                    stmt = stmt.outerjoin(jn)

            for_equality = True
            for key, value in filters.items():
                if key.startswith("!"):
                    key = key[1:]
                    for_equality = False

                if filter_defs and key in filter_defs:
                    column = filter_defs[key]
                else:
                    column = getattr(cls, key)

                if not isinstance(value, list):
                    value = to_list(value)

                is_date = any(isinstance(v, date) for v in value)

                if isinstance(column.type, ARRAY):
                    filter_expr = column.overlap(value)
                else:
                    if is_date:
                        column = cast(column, Date)
                    filter_expr = column.in_(value)

                if for_equality:
                    stmt = stmt.where(filter_expr)
                else:
                    stmt = stmt.where(~filter_expr)

            result = await s.execute(stmt)
            return list(result.scalars().all())

        if session is not None:
            return await _exec(session)
        async with db.session_scope() as s:
            return await _exec(s)

    # ------------------------------------------------------------------- get --

    @classmethod
    async def get(cls: Type[T], *, session: AsyncSession | None = None, **kwargs) -> T:
        async def _exec(s: AsyncSession) -> T:
            if "id" in kwargs and len(kwargs) == 1:
                result = await s.get(cls, kwargs["id"])
            else:
                stmt = select(cls)
                for key, value in kwargs.items():
                    stmt = stmt.where(getattr(cls, key) == value)
                result = (await s.execute(stmt)).scalars().first()

            if not result:
                if error := cls.__errors__.get("_error"):
                    raise error(**kwargs)
                raise NoDataFound(key=kwargs, messages="No data found in DB")
            return result

        if session is not None:
            return await _exec(session)
        async with db.session_scope() as s:
            return await _exec(s)

    # ---------------------------------------------------------------- update --

    async def update(
        self: T,
        force_update: bool = False,
        *,
        session: AsyncSession | None = None,
        **kwargs,
    ) -> T:
        async def _exec(s: AsyncSession) -> T:
            merged = await s.merge(self)
            for key, value in kwargs.items():
                if force_update or value is not None:
                    setattr(merged, key, value)
            await s.flush()
            return merged

        if session is not None:
            return await _exec(session)
        async with db.session_scope() as s:
            return await _exec(s)

    # ---------------------------------------------------------------- create --

    async def create(self: T, *, session: AsyncSession | None = None) -> T:
        async def _exec(s: AsyncSession) -> T:
            s.add(self)
            await s.flush()
            await s.refresh(self)
            return self

        if session is not None:
            return await _exec(session)
        async with db.session_scope() as s:
            return await _exec(s)

    # ---------------------------------------------------------------- delete --

    async def delete(self: T, *, session: AsyncSession | None = None) -> T:
        async def _exec(s: AsyncSession) -> T:
            merged = await s.merge(self)
            await s.delete(merged)
            return self

        if session is not None:
            return await _exec(session)
        async with db.session_scope() as s:
            return await _exec(s)
