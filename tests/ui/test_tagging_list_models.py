from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from exif_turbo.models.image_tag import ImageTag, TagProvenance
from exif_turbo.models.tag_proposal import TagProposal
from exif_turbo.models.tgm import TgmCategory, TgmConcept
from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
)
from exif_turbo.tagging.tagging_service import AggregatedConceptState, TagMembership
from exif_turbo.ui.models.accepted_tag_list_model import AcceptedTagListModel
from exif_turbo.ui.models.marked_tag_list_model import MarkedTagListModel
from exif_turbo.ui.models.pending_proposal_list_model import PendingProposalListModel
from exif_turbo.ui.models.free_tag_list_model import FreeTagListModel
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


def test_tgm_search_list_model_exposes_vocabulary_roles(qtbot: QtBot) -> None:
    # Arrange
    model = TgmSearchListModel()
    concept = VocabularyConcept(
        concept_id="wikidata:Q4421",
        category=VocabularyCategory.SUBJECT,
        canonical_label="forest",
        localized_terms=(
            LocalizedVocabularyTerms("en", "forest", ("wood",)),
            LocalizedVocabularyTerms("de", "Wald", ("Waldgebiet",)),
            LocalizedVocabularyTerms("fr", "forêt", ("bois",)),
            LocalizedVocabularyTerms("it", "foresta", ("selva",)),
        ),
        source_uri="https://www.wikidata.org/entity/Q4421",
        license_id="CC0-1.0",
    )
    model.set_localization(
        lambda _concept_id: concept.preferred_label("de"),
        lambda _concept_id: concept.aliases("de"),
    )

    # Act
    model.set_rows([concept])

    # Assert
    assert model.data(model.index(0), model.LabelRole) == "Wald"
    assert model.data(model.index(0), model.CategoriesRole) == ["subject"]
    assert model.data(model.index(0), model.AliasesRole) == ["Waldgebiet"]
    assert model.data(model.index(0), model.CanonicalLabelRole) == "forest"


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


def test_pending_proposal_list_model_finds_and_removes_ephemeral_row(
    qtbot: QtBot,
) -> None:
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
    model.set_rows([proposal])

    # Act
    found = model.find(proposal.concept_id, proposal.provider_fingerprint)
    model.remove(proposal)

    # Assert
    assert found is proposal
    assert model.rowCount() == 0


def test_free_tag_list_model_exposes_label_rows(qtbot: QtBot) -> None:
    # Arrange
    model = FreeTagListModel()

    # Act
    model.set_rows(("Family", "Summer 2026"))

    # Assert
    assert model.rowCount() == 2
    assert model.data(model.index(0), model.LabelRole) == "Family"
    assert model.data(model.index(1), Qt.DisplayRole) == "Summer 2026"


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