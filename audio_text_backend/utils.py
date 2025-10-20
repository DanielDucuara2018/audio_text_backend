import secrets
from dataclasses import fields
from typing import Any, Optional, Type, TypeVar

from apischema import deserialize

_config_fields: dict[Type, Optional[Any]] = {}

Cls = TypeVar("Cls", bound=Type)


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


def load_configuration_data(config: dict[str, Any]) -> None:
    for key, _ in _config_fields.items():
        _config_fields[key] = deserialize(key, config)


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
