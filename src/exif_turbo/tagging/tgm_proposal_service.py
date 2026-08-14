from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from ..data.image_index_repository import ImageIndexRepository
from ..models.tag_proposal import (
    ProposalBatchResult,
    ProposalGenerationResult,
    ProposalGenerationStatus,
    TagProposal,
    TagProposalStatus,
)
from ..models.tgm_vector import TgmVectorFingerprint
from .tgm_clip_proposal_provider import TgmClipProposalProvider


class TgmProposalService:
    def __init__(
        self,
        image_repository: ImageIndexRepository,
        provider: TgmClipProposalProvider,
    ) -> None:
        self._image_repository = image_repository
        self._provider = provider

    def generate(
        self,
        image_paths: Iterable[str],
        expected_fingerprint: TgmVectorFingerprint,
        *,
        top_k: int,
        threshold: float,
        auto_accept_threshold: float | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ProposalBatchResult:
        paths = tuple(image_paths)
        results: list[ProposalGenerationResult] = []
        provider_id = expected_fingerprint.identifier
        for index, image_path in enumerate(paths):
            if cancel_check is not None and cancel_check():
                return ProposalBatchResult(tuple(results), True)
            result = self._provider.propose(
                image_path,
                expected_fingerprint,
                top_k=top_k,
                threshold=threshold,
            )
            if result.status is ProposalGenerationStatus.COMPLETED:
                accepted = {
                    tag.concept_id
                    for tag in self._image_repository.get_accepted_tags(image_path)
                }
                rejected = {
                    proposal.concept_id
                    for proposal in self._image_repository.get_proposals(
                        image_path,
                        provider_fingerprint=provider_id,
                        status=TagProposalStatus.REJECTED,
                    )
                }
                seen: set[str] = set()
                filtered: list[TagProposal] = []
                for proposal in result.proposals:
                    if (
                        proposal.concept_id in accepted
                        or proposal.concept_id in rejected
                        or proposal.concept_id in seen
                    ):
                        continue
                    seen.add(proposal.concept_id)
                    filtered.append(replace(proposal, rank=len(filtered) + 1))
                auto_candidates = tuple(
                    proposal
                    for proposal in filtered
                    if auto_accept_threshold is not None
                    and proposal.score >= auto_accept_threshold
                )
                result = replace(
                    result,
                    proposals=tuple(filtered),
                    auto_candidates=auto_candidates,
                )
            results.append(result)
            if on_progress is not None:
                on_progress(index + 1, len(paths), image_path)
        return ProposalBatchResult(tuple(results), False)