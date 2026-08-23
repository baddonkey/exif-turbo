from __future__ import annotations

import pytest

from exif_turbo.models.vocabulary import (
    LocalizedVocabularyTerms,
    VocabularyCategory,
    VocabularyConcept,
)


def _localized_terms() -> tuple[LocalizedVocabularyTerms, ...]:
    return (
        LocalizedVocabularyTerms("de", "Wald", ("Forst",)),
        LocalizedVocabularyTerms("en", "Forest", ("Woods",)),
        LocalizedVocabularyTerms("fr", "Forêt", ("Bois",)),
        LocalizedVocabularyTerms("it", "Foresta", ("Bosco",)),
    )


def test_vocabulary_concept_complete_required_locales_is_valid() -> None:
    # Arrange / Act
    concept = VocabularyConcept(
        concept_id="wikidata:Q4421",
        category=VocabularyCategory.SUBJECT,
        canonical_label="Forest",
        localized_terms=_localized_terms(),
        source_uri="https://www.wikidata.org/entity/Q4421",
        license_id="CC0-1.0",
    )

    # Assert
    assert concept.preferred_label("fr") == "Forêt"
    assert concept.aliases("de") == ("Forst",)


def test_vocabulary_concept_missing_required_locale_raises_value_error() -> None:
    # Arrange
    incomplete_terms = tuple(
        terms for terms in _localized_terms() if terms.locale != "it"
    )

    # Act / Assert
    with pytest.raises(ValueError, match="required locales"):
        VocabularyConcept(
            concept_id="wikidata:Q4421",
            category=VocabularyCategory.SUBJECT,
            canonical_label="Forest",
            localized_terms=incomplete_terms,
            source_uri="https://www.wikidata.org/entity/Q4421",
            license_id="CC0-1.0",
        )


def test_vocabulary_concept_invalid_wikidata_id_raises_value_error() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="wikidata:Q"):
        VocabularyConcept(
            concept_id="wikidata:Q0",
            category=VocabularyCategory.GENRE_FORMAT,
            canonical_label="Forest",
            localized_terms=_localized_terms(),
            source_uri="https://www.wikidata.org/entity/Q0",
            license_id="CC0-1.0",
        )