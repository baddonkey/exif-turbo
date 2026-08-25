from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TagProposalStatus(StrEnum):
    PENDING = "pending"
    REJECTED = "rejected"


class ProposalGenerationStatus(StrEnum):
    COMPLETED = "completed"
    AI_SCAN_REQUIRED = "ai_scan_required"
    TGM_INDEX_REQUIRED = "tgm_index_required"


class TagProposalKind(StrEnum):
    VISUAL_CONCEPT = "visual_concept"
    PUBLIC_FIGURE = "public_figure"


@dataclass(frozen=True)
class TagProposal:
    image_path: str
    concept_id: str
    label: str
    category: str
    provider_fingerprint: str
    score: float
    rank: int
    status: TagProposalStatus = TagProposalStatus.PENDING
    provider_model: str = "clip"
    winning_view_id: str = "full"
    winning_locale: str = "en"
    kind: TagProposalKind = TagProposalKind.VISUAL_CONCEPT


@dataclass(frozen=True)
class ProposalGenerationResult:
    image_path: str
    status: ProposalGenerationStatus
    proposals: tuple[TagProposal, ...] = ()
    auto_candidates: tuple[TagProposal, ...] = ()


@dataclass(frozen=True)
class ProposalBatchResult:
    results: tuple[ProposalGenerationResult, ...]
    cancelled: bool