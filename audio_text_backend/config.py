"""Configuration module for the application."""

import logging
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

from .utils import build_config_dict, load_configuration, load_configuration_data

ROOT = Path(__file__).parents[1].resolve()

logger = logging.getLogger(__name__)


@dataclass
class AWS:
    """AWS S3 configuration for file storage."""

    bucket_name: str
    access_key: str
    secret_key: str
    region: str


@dataclass
class Middleware:
    """API middleware configuration for CORS and rate limiting."""

    cors_origins: list[str]
    requests_per_minute: int = 60
    requests_per_hour: int = 1000


@dataclass
class Database:
    """PostgreSQL database configuration."""

    database: str
    host: str
    password: str
    port: int
    user: str
    ref_table: str
    skip_alembic_migration: bool = False


@dataclass
class File:
    """File upload validation configuration."""

    max_size_mb: int
    allowed_audio_extensions: list[str]


@dataclass
class Whisper:
    """Faster-whisper model configuration."""

    device: str
    compute_type: str
    cpu_threads: int
    beam_size: int
    vad_filter: bool
    vad_min_silence_duration_ms: int
    word_timestamps: bool = False


@dataclass
class Email:
    """Email sender configuration."""

    from_address: str
    from_name: str
    sendgrid_api_key: str
    enabled: bool = True


@dataclass
class PubSub:
    """Google Cloud Pub/Sub configuration."""

    project_id: str
    jobs_topic: str
    status_topic: str
    jobs_subscription: str
    status_subscription: str
    # Push subscription endpoint for status updates (parameterised per environment)
    api_push_endpoint: str
    # Per-tier job subscriptions used by Cloud Run Job triggers in production.
    # Local dev uses the single jobs_subscription for the pull worker.
    jobs_subscription_small: str = ""
    jobs_subscription_medium: str = ""
    jobs_subscription_large: str = ""


@dataclass
class Worker:
    """Cloud Run Job worker configuration."""

    # Model tier this job instance processes: small | medium | large.
    # Empty string for local dev (local_worker handles all tiers via a single subscription).
    tier: str = ""


@load_configuration
@dataclass
class Config:
    """Main configuration container."""

    middleware: Middleware
    database: Database
    pubsub: PubSub
    aws: AWS
    file: File
    whisper: Whisper
    email: Email
    worker: Worker


def bootstrap_configuration(path: str | Path = ROOT.joinpath("config.ini")) -> None:
    """Load configuration from config.ini."""
    logger.info("Loading configuration from file %s", path)
    config = ConfigParser()
    config.read(path)
    load_configuration_data(build_config_dict(config))


# Auto-load on import
bootstrap_configuration()
