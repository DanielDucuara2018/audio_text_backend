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
class Celery:
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str


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
    whisper_model: str


@load_configuration
@dataclass
class Config:
    database: Database
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
