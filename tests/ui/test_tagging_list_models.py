from __future__ import annotations

from datetime import UTC, datetime

from pytestqt.qtbot import QtBot

from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.tag_proposal import TagProposal
from exif_turbo.models.tgm import TgmCategory, TgmConcept
from exif_turbo.tagging.tagging_service import AggregatedConceptState, TagMembership
from exif_turbo.ui.models.accepted_tag_list_model import AcceptedTagListModel
from exif_turbo.ui.models.marked_tag_list_model import MarkedTagListModel
from exif_turbo.ui.models.pending_proposal_list_model import PendingProposalListModel
from exif_turbo.ui.models.tgm_search_list_model import TgmSearchListModel


def _concept() -> TgmConcept:
    return TgmConcept(
        concept_id="loc-tgm:tgm000001",
        tnr="tgm000001",
        label="Forests",
        categories=(TgmCategory.SUBJECT,),
        aliases=("Woods",),
    )


def test_accepted_tag_list_model_exposes_stable_roles_and_resets(
    qtbot: QtBot,
) -> None:
    # Arrange
    model = AcceptedTagListModel()
    tag = ImageTag(
        concept_id="loc-tgm:tgm000001",
        label="Forests",
        category="subject",
        provenance=TagProvenance(
            method="manual",
            accepted_at="2026-08-09T12:00:00Z",
            vocabulary_checksum="sha256:snapshot",
        ),
    )

    # Act
    model.set_rows([tag])

    # Assert
    assert model.roleNames()[model.ConceptIdRole] == b"conceptId"
    assert model.data(model.index(0), model.LabelRole) == "Forests"
    assert model.rowCount() == 1


def test_tgm_search_list_model_exposes_categories_and_aliases(qtbot: QtBot) -> None:
    # Arrange
    model = TgmSearchListModel()

    # Act
    model.set_rows([_concept()])

    # Assert
    assert model.data(model.index(0), model.CategoriesRole) == ["subject"]
    assert model.data(model.index(0), model.AliasesRole) == ["Woods"]


def test_pending_proposal_list_model_exposes_score_and_provider(qtbot: QtBot) -> None:
    # Arrange
    model = PendingProposalListModel()
    proposal = TagProposal(
        image_path="/photos/photo.jpg",
        concept_id="loc-tgm:tgm000001",
        label="Forests",
        category="subject",
        provider_fingerprint="fingerprint",
        score=0.75,
        rank=1,
    )

    # Act
    model.set_rows([proposal])

    # Assert
    assert model.data(model.index(0), model.ScoreRole) == 0.75
    assert model.data(model.index(0), model.ProviderFingerprintRole) == "fingerprint"


def test_marked_tag_list_model_exposes_aggregate_count_and_membership(
    qtbot: QtBot,
) -> None:
    # Arrange
    model = MarkedTagListModel()
    state = AggregatedConceptState(_concept(), 2, TagMembership.SOME)

    # Act
    model.set_rows([state])

    # Assert
    assert model.data(model.index(0), model.CountRole) == 2
    assert model.data(model.index(0), model.MembershipRole) == "some"