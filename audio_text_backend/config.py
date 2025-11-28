"""Configuration module for the application."""

import logging
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

from .utils import build_config_dict, load_configuration, load_configuration_data

ROOT = Path(__file__).parents[1].resolve()

logger = logging.getLogger(__name__)


@dataclass
class Redis:
    """Redis configuration for Celery broker/backend and pub/sub."""

    host: str
    port: int
    pub_sub_channel: str


@dataclass
class AWS:
    """AWS S3 configuration for file storage."""

    bucket_name: str
    access_key: str
    secret_key: str
    region: str


@dataclass
class Queue:
    """Celery queue configuration with retry policy."""

    queue_name: str
    retry_policy_max_retries: int = 3
    retry_policy_interval_start: int = 0
    retry_policy_interval_step: int = 60
    retry_policy_interval_max: int = 300


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
    force_recreate: bool = False
    alembic_migration: bool = True


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
class Celery:
    """Celery configuration."""

    queues: dict[str, Queue]
    serialization_format: str = "json"
    timezone: str = "UTC"
    enable_utc: bool = True
    task_track_started: bool = True
    task_acks_late: bool = True
    worker_prefetch_multiplier: int = 1
    worker_disable_rate_limits: bool = True
    worker_max_tasks_per_child: int = 10
    task_time_limit: int = 600
    task_soft_time_limit: int = 480
    task_default_retry_delay: int = 60
    task_max_retries: int = 3
    worker_autoscaler: str = "celery.worker.autoscale:Autoscaler"


@load_configuration
@dataclass
class Config:
    """Main configuration container."""

    middleware: Middleware
    database: Database
    redis: Redis
    celery: Celery
    aws: AWS
    file: File
    whisper: Whisper
    email: Email


def bootstrap_configuration(path: str | Path = ROOT.joinpath("config.ini")) -> None:
    """Load configuration from config.ini."""
    logger.info("Loading configuration from file %s", path)
    config = ConfigParser()
    config.read(path)
    load_configuration_data(build_config_dict(config))


# Auto-load on import
bootstrap_configuration()
