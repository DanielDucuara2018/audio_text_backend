import os
import secrets
from configparser import ConfigParser
from dataclasses import fields
from typing import Any, Optional, Type, TypeVar, cast

from apischema import deserialize

_config_fields: dict[Type, Optional[Any]] = {}

Cls = TypeVar("Cls", bound=Type)

T = TypeVar("T")

BOOL_VALUES = {"1", "true", "yes", "on", "True", "Yes", "On"}


class ConfigurationField:
    def __init__(self, name: str):
        self.name = name

    def __get__(self, instance, owner):
        assert instance is None
        try:
            return getattr(_config_fields[owner], self.name)
        except AttributeError:
            raise RuntimeError("Configuration not loaded") from None
        except KeyError:
            raise RuntimeError("Configuration is not root") from None


def load_configuration(cls: Cls) -> Cls:
    for field_ in fields(cls):
        setattr(cls, field_.name, ConfigurationField(field_.name))
    _config_fields[cls] = None
    return cls


def build_config_dict(config: ConfigParser) -> dict:
    result = {}

    for section in config.sections():
        parts = section.split(":")
        node = result

        for p in parts[:-1]:
            node = node.setdefault(p, {})

        last = parts[-1]
        if last in node:
            node[last].update(dict(config.items(section)))
        else:
            node[last] = dict(config.items(section))

    return result


def coerce(cls: type[T], data) -> T:
    """Only coerce int to bool."""
    if isinstance(data, dict):
        return data

    if "env" in data.lower():
        if data in os.environ:
            data = os.environ[data]
        else:
            raise RuntimeError(f"Environment variable {data} not set")

    if cls in {int, str, float}:
        data = cast(T, cls(data))
    elif cls is list:
        data = cast(T, cls(data.split(",")))
    elif cls is bool:
        data = cast(T, cls(data in BOOL_VALUES))

    return data


def load_configuration_data(config: dict[str, Any]) -> None:
    for key, _ in _config_fields.items():
        _config_fields[key] = deserialize(key, config, coerce=coerce)


def idun(prefix: str, nbytes: int = 16) -> str:
    return f"{prefix}-{secrets.token_hex(nbytes)}"


def to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]
