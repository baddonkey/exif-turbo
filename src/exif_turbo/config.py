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


def database_data_dir(db_path: Path) -> Path:
    """Return the private artifact directory for a database file.

    Canonical named databases already live in ``.../<name>/<name>.db`` and
    keep that existing directory. Other database files use a hidden sibling
    directory so equal filenames in different locations never share caches.
    """
    path = db_path.expanduser()
    if path.parent.name == path.stem:
        return path.parent
    return path.parent / f".{path.stem}.exif-turbo"


def thumb_cache_dir(db_path: Path) -> Path:
    return database_data_dir(db_path) / "thumbs"


def ai_index_path(db_path: Path) -> Path:
    """Path to the FAISS vector index file for the given database."""
    return database_data_dir(db_path) / "ai_index.faiss"


def ai_id_map_path(db_path: Path) -> Path:
    """Path to the JSON id-map (FAISS integer ID → image path) for the given database."""
    return database_data_dir(db_path) / "ai_id_map.json"


def ai_vector_metadata_path(db_path: Path) -> Path:
    """Path to model and integrity metadata for the AI vector index."""
    return database_data_dir(db_path) / "ai_index_meta.json"


def settings_path(db_path: Path) -> Path:
    """Per-database settings file.

    Stored at ``~/.exif-turbo/data/<db_stem>/settings.json`` so each database
    can have independent settings (worker count, blacklist, …).
    """
    return database_data_dir(db_path) / "settings.json"


def bundled_vocabulary_path() -> Path:
    """Bundled offline Wikidata controlled-vocabulary snapshot."""
    return Path(__file__).resolve().parent / "assets" / "wikidata-vocabulary-v2.json.gz"


def tgm_snapshot_path(db_path: Path) -> Path:
    """Active normalized TGM snapshot for the given database."""
    return database_data_dir(db_path) / "tgm" / "tgm-snapshot.json.gz"


def tgm_localization_pack_path(db_path: Path) -> Path:
    """Active independently sourced TGM localization overlay."""
    return tgm_snapshot_path(db_path).parent / "tgm-localizations.json.gz"


def tgm_work_dir(db_path: Path) -> Path:
    """Temporary managed-update workspace for the given database."""
    return tgm_snapshot_path(db_path).parent / "work"


def tgm_term_index_path(db_path: Path) -> Path:
    """FAISS index containing TGM concept text vectors."""
    return tgm_snapshot_path(db_path).parent / "tgm_terms.faiss"


def tgm_concept_map_path(db_path: Path) -> Path:
    """FAISS row-to-concept map for the TGM term index."""
    return tgm_snapshot_path(db_path).parent / "tgm_concept_map.json"


def tgm_vector_metadata_path(db_path: Path) -> Path:
    """Fingerprint and integrity metadata for the TGM term index."""
    return tgm_snapshot_path(db_path).parent / "tgm_vector_metadata.json"


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
