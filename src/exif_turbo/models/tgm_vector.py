from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any


@dataclass(frozen=True)
class TgmVectorFingerprint:
    vocabulary: str
    snapshot_version: int
    source_dump_sha256: str
    manifest_sha256: str
    prompt_version: int
    prompt_strategy: str
    prompt_locales: tuple[str, ...]
    model_name: str
    pretrained: str
    dimension: int

    def __post_init__(self) -> None:
        if self.vocabulary != "wikidata":
            raise ValueError("vector fingerprint vocabulary must be wikidata")
        if self.snapshot_version <= 0 or self.prompt_version <= 0:
            raise ValueError("snapshot and prompt versions must be positive")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_dump_sha256):
            raise ValueError("source_dump_sha256 must be lowercase SHA256")
        if not re.fullmatch(r"[0-9a-f]{64}", self.manifest_sha256):
            raise ValueError("manifest_sha256 must be lowercase SHA256")
        if not self.prompt_strategy.strip():
            raise ValueError("prompt_strategy must not be empty")
        if self.prompt_locales != ("en", "de", "fr", "it"):
            raise ValueError("prompt_locales must be exactly en, de, fr, it")
        if not self.model_name.strip() or not self.pretrained.strip():
            raise ValueError("model fields must not be empty")
        if self.dimension <= 0:
            raise ValueError("dimension must be positive")

    @property
    def identifier(self) -> str:
        payload = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "TgmVectorFingerprint":
        if not isinstance(value, dict):
            raise ValueError("controlled-vocabulary vector fingerprint must be an object")
        expected_keys = {
            "vocabulary",
            "snapshot_version",
            "source_dump_sha256",
            "manifest_sha256",
            "prompt_version",
            "prompt_strategy",
            "prompt_locales",
            "model_name",
            "pretrained",
            "dimension",
        }
        if set(value) != expected_keys:
            raise ValueError("unsupported controlled-vocabulary vector fingerprint")
        prompt_locales = value["prompt_locales"]
        if not isinstance(prompt_locales, list) or not all(
            isinstance(locale, str) for locale in prompt_locales
        ):
            raise ValueError("prompt_locales must be an array of strings")
        integer_fields = ("snapshot_version", "prompt_version", "dimension")
        if any(
            not isinstance(value[field], int) or isinstance(value[field], bool)
            for field in integer_fields
        ):
            raise ValueError("vector fingerprint version and dimension fields must be integers")
        string_fields = expected_keys.difference(integer_fields).difference(
            {"prompt_locales"}
        )
        if any(not isinstance(value[field], str) for field in string_fields):
            raise ValueError("vector fingerprint text fields must be strings")
        return cls(
            vocabulary=value["vocabulary"],
            snapshot_version=value["snapshot_version"],
            source_dump_sha256=value["source_dump_sha256"],
            manifest_sha256=value["manifest_sha256"],
            prompt_version=value["prompt_version"],
            prompt_strategy=value["prompt_strategy"],
            prompt_locales=tuple(prompt_locales),
            model_name=value["model_name"],
            pretrained=value["pretrained"],
            dimension=value["dimension"],
        )


@dataclass(frozen=True)
class TgmVectorHit:
    concept_id: str
    locale: str
    score: float
    rank: int


@dataclass(frozen=True)
class TgmVectorBuildResult:
    completed: bool
    indexed_count: int