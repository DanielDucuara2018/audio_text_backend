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
class Database:
    database: str
    host: str
    password: str
    port: str
    user: str
    ref_table: str
    force_recreate: str = "0"


@dataclass
class Redis:
    host: str
    port: str
    pub_sub_channel: str


@dataclass
class Celery:
    # Queue configuration
    queue_name: str
    routing_key: str

    # Serialization settings
    serialization_format: str = "json"
    timezone: str = "UTC"
    enable_utc: str = "1"
    task_track_started: str = "1"

    # Worker configuration
    task_acks_late: str = "1"
    worker_prefetch_multiplier: str = "1"
    worker_disable_rate_limits: str = "1"
    worker_max_tasks_per_child: str = "10"

    # Task time limits (in seconds)
    task_time_limit: str = "1800"  # 30 minutes
    task_soft_time_limit: str = "1500"  # 25 minutes

    # Retry settings
    task_default_retry_delay: str = "60"  # 1 minute
    task_max_retries: str = "3"

    # Auto-scaling
    worker_autoscaler: str = "celery.worker.autoscale:Autoscaler"

    # Retry policy settings
    retry_policy_max_retries: str = "3"
    retry_policy_interval_start: str = "0"
    retry_policy_interval_step: str = "60"
    retry_policy_interval_max: str = "300"


@dataclass
class AWS:
    bucket_name: str
    access_key: str
    secret_key: str
    region: str


@dataclass
class File:
    max_size_mb: str
    allowed_audio_extensions: str


@load_configuration
@dataclass
class Config:
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
