from __future__ import annotations

from dataclasses import dataclass
import os


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


@dataclass(frozen=True)
class AppConfig:
    skip_dotfiles: bool = True


def load_config() -> AppConfig:
    return AppConfig(skip_dotfiles=_env_bool("EXIF_TURBO_SKIP_DOTFILES", True))
