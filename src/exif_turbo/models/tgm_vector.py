from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class TgmVectorFingerprint:
    raw_tgm_sha256: str
    normalization_version: int
    prompt_version: int
    model_name: str
    pretrained: str
    dimension: int

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
            raise ValueError("TGM vector fingerprint must be an object")
        return cls(
            raw_tgm_sha256=str(value["raw_tgm_sha256"]),
            normalization_version=int(value["normalization_version"]),
            prompt_version=int(value["prompt_version"]),
            model_name=str(value["model_name"]),
            pretrained=str(value["pretrained"]),
            dimension=int(value["dimension"]),
        )


@dataclass(frozen=True)
class TgmVectorHit:
    concept_id: str
    score: float
    rank: int


@dataclass(frozen=True)
class TgmVectorBuildResult:
    completed: bool
    indexed_count: int