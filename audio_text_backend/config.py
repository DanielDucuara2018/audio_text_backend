import logging
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

from .utils import load_configuration, load_configuration_data

ROOT = Path(__file__).parents[1]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


@dataclass
class Middleware:
    cors_origins: list[str]
    requests_per_minute: int = 60
    requests_per_hour: int = 1000


@dataclass
class Database:
    database: str
    host: str
    password: str
    port: int
    user: str
    ref_table: str
    force_recreate: bool = False


@dataclass
class Redis:
    host: str
    port: int
    pub_sub_channel: str


@dataclass
class Celery:
    # Queue configuration
    queue_name: str
    routing_key: str

    # Serialization settings
    serialization_format: str = "json"
    timezone: str = "UTC"
    enable_utc: bool = True
    task_track_started: bool = True

    # Worker configuration
    task_acks_late: bool = True
    worker_prefetch_multiplier: int = 1
    worker_disable_rate_limits: bool = True
    worker_max_tasks_per_child: int = 10

    # Task time limits (in seconds)
    task_time_limit: int = 1800  # 30 minutes
    task_soft_time_limit: int = 1500  # 25 minutes

    # Retry settings
    task_default_retry_delay: int = 60  # 1 minute
    task_max_retries: int = 3

    # Auto-scaling
    worker_autoscaler: str = "celery.worker.autoscale:Autoscaler"

    # Retry policy settings
    retry_policy_max_retries: int = 3
    retry_policy_interval_start: int = 0
    retry_policy_interval_step: int = 60
    retry_policy_interval_max: int = 300


@dataclass
class AWS:
    bucket_name: str
    access_key: str
    secret_key: str
    region: str


@dataclass
class File:
    max_size_mb: int
    allowed_audio_extensions: list[str]


@load_configuration
@dataclass
class Config:
    middleware: Middleware
    database: Database
    redis: Redis
    celery: Celery
    aws: AWS
    file: File


def bootstrap_configuration(path: str | Path = ROOT.joinpath("config.ini")) -> None:
    logger.info("Loading configuration from file %s", path)
    config = ConfigParser()
    config.read(path)
    config_dict = {section: dict(config.items(section)) for section in config.sections()}
    load_configuration_data(config_dict)


bootstrap_configuration()
