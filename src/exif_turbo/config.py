from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def default_db_path() -> Path:
    return Path.home() / ".exif-turbo" / "data" / "index" / "index.db"


def db_path_for_name(name: str) -> Path:
    """Resolve a bare database name to its canonical location.

    The name may be:
    - ``"index"`` or ``"work"`` → ``~/.exif-turbo/data/<name>/<name>.db``
    - An absolute path (legacy / scripts) — returned as-is.
    - A relative path containing a directory separator — resolved relative to cwd.
    """
    p = Path(name)
    if p.is_absolute() or len(p.parts) > 1:
        return p if p.suffix else p.with_suffix(".db")
    stem = p.stem  # strip any trailing .db the user may have typed
    return Path.home() / ".exif-turbo" / "data" / stem / f"{stem}.db"


def thumb_cache_dir(db_path: Path) -> Path:
    return Path.home() / ".exif-turbo" / "data" / db_path.stem / "thumbs"


def settings_path(db_path: Path) -> Path:
    """Per-database settings file.

    Stored at ``~/.exif-turbo/data/<db_stem>/settings.json`` so each database
    can have independent settings (worker count, blacklist, …).
    """
    return Path.home() / ".exif-turbo" / "data" / db_path.stem / "settings.json"


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
