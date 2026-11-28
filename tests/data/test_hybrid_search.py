from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from exif_turbo.data.ai_vector_backend import AiVectorBackend
from exif_turbo.data.hybrid_search import (
    HybridSearchCanceled,
    HybridSearchStaleError,
    build_hybrid_results,
)
from exif_turbo.data.image_index_repository import ImageIndexRepository


def _insert(
    repo: ImageIndexRepository, tmp_path: Path, name: str, text: str, captured_at: int
) -> str:
    path = str(tmp_path / name)
    repo.upsert_image(path, name, 1.0, 100, {}, text, captured_at=captured_at)
    return path


def _vector_backend(hits: list[tuple[str, float]]) -> Mock:
    backend = Mock(spec=AiVectorBackend)
    backend.search_filtered.side_effect = (
        lambda _vector, allowed, **_kwargs: [
            (path, score) for path, score in hits if path in allowed
        ]
    )
    return backend


def test_hybrid_discovery_unions_ranks_and_preserves_pre_date_facets(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    first = _insert(repo, tmp_path, "first.jpg", "Canon", 1577836800)
    second = _insert(repo, tmp_path, "second.jpg", "Nikon", 1609459200)
    both = _insert(repo, tmp_path, "both.jpg", "Canon", 1609459200)
    fourth = _insert(repo, tmp_path, "fourth.jpg", "Sony", 1577836800)
    repo.commit()
    backend = _vector_backend([(second, 0.9), (both, 0.8), (fourth, 0.7)])

    results = build_hybrid_results(repo, backend, "Canon", np.ones(1), date_from=1609459200)

    assert [match.path for match in results.matches] == [both, second]
    assert results.total_count == 2
    assert set(results.facet_paths) == {first, second, both, fourth}
    assert results.matches[0].relevance == pytest.approx(1 / 61 + 1 / 62)
    assert backend.search_filtered.call_count == 1


def test_hybrid_format_facets_ignore_selected_format_but_respect_date(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    jpg = _insert(repo, tmp_path, "one.jpg", "Canon", 1609459200)
    png = _insert(repo, tmp_path, "two.png", "Nikon", 1609459200)
    old = _insert(repo, tmp_path, "old.png", "Canon", 1577836800)
    repo.commit()
    backend = _vector_backend([(png, 0.9)])

    results = build_hybrid_results(
        repo, backend, "Canon", np.ones(1), ext_filter="jpg", date_from=1609459200
    )

    assert [match.path for match in results.matches] == [jpg]
    assert set(results.facet_paths) == {jpg}
    assert set(results.format_paths) == {jpg, png}
    assert old not in results.format_paths
    assert backend.search_filtered.call_count == 1


def test_hybrid_explicit_and_filters_semantic_candidates_before_ranking(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    first = _insert(repo, tmp_path, "first.jpg", "Canon", 1609459200)
    second = _insert(repo, tmp_path, "second.jpg", "Nikon", 1609459200)
    both = _insert(repo, tmp_path, "both.jpg", "Canon", 1609459200)
    repo.commit()
    backend = _vector_backend([(second, 0.95), (both, 0.8), (first, 0.7)])

    results = build_hybrid_results(
        repo, backend, 'Canon ai:="deer"', np.ones(1), ext_filter="jpg"
    )

    assert [match.path for match in results.matches] == [both, first]
    assert backend.search_filtered.call_args.args[1] == {first, both}
    assert set(results.facet_paths) == {first, both}
    assert results.matches[0].relevance == pytest.approx(0.8)


def test_hybrid_paging_hydrates_in_order_without_requerying_vectors(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    paths = [_insert(repo, tmp_path, f"{i}.jpg", "Canon", 1609459200) for i in range(5)]
    repo.commit()
    backend = _vector_backend([(path, 0.9 - i * 0.1) for i, path in enumerate(paths)])
    results = build_hybrid_results(repo, backend, "Canon", np.ones(1))

    rows = (
        results.hydrate_page(repo, 0, 2)
        + results.hydrate_page(repo, 2, 2)
        + results.hydrate_page(repo, 4, 2)
    )

    assert [row[0] for row in rows] == [match.image_id for match in results.matches]
    assert len({row[0] for row in rows}) == 5
    assert backend.search_filtered.call_count == 1


def test_hybrid_page_deleted_image_rejects_stale_generation(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    _insert(repo, tmp_path, "one.jpg", "Canon", 1609459200)
    repo.commit()
    results = build_hybrid_results(repo, None, "", None)
    repo.delete_missing([])
    repo.commit()

    with pytest.raises(HybridSearchStaleError):
        results.hydrate_page(repo, 0, 10)


def test_hybrid_semantic_unavailable_does_not_broaden_explicit_query(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    _insert(repo, tmp_path, "one.jpg", "Canon", 1609459200)
    repo.commit()

    with pytest.raises(RuntimeError, match="AI search is unavailable"):
        build_hybrid_results(repo, None, 'Canon ai:="deer"', None)


def test_hybrid_canceled_search_does_not_return_results(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    _insert(repo, tmp_path, "one.jpg", "Canon", 1609459200)
    repo.commit()

    with pytest.raises(HybridSearchCanceled):
        build_hybrid_results(repo, None, "", None, canceled=lambda: True)


def test_hybrid_discovery_cap_keeps_all_metadata_and_uncapped_facets(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    semantic_paths = [
        _insert(repo, tmp_path, f"{i}.jpg", "Nikon", 1609459200)
        for i in range(2001)
    ]
    metadata_only = _insert(repo, tmp_path, "metadata.jpg", "Canon", 1609459200)
    repo.commit()
    backend = _vector_backend([(path, 0.9) for path in semantic_paths])

    results = build_hybrid_results(repo, backend, "Canon", np.ones(1))

    assert len(results.matches) == 2001
    assert metadata_only in {match.path for match in results.matches}
    assert results.total_count == 2002
    assert set(results.facet_paths) == set(semantic_paths) | {metadata_only}
    facet_paths_with_duplicate = list(results.facet_paths) + [semantic_paths[0]]
    assert repo.get_year_counts_by_paths(facet_paths_with_duplicate) == [(2021, 2002)]
    assert repo.get_format_counts_by_paths(facet_paths_with_duplicate) == [("jpg", 2002)]


def test_hybrid_explicit_sort_and_marked_scope_apply_to_union(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    first = _insert(repo, tmp_path, "a.jpg", "Canon", 1609459200)
    second = _insert(repo, tmp_path, "b.jpg", "Nikon", 1609459200)
    excluded = _insert(repo, tmp_path, "c.jpg", "Canon", 1609459200)
    repo.conn.execute("UPDATE images SET marked = 1 WHERE path IN (?, ?)", (first, second))
    repo.commit()
    backend = _vector_backend([(excluded, 0.99), (second, 0.8)])

    results = build_hybrid_results(
        repo, backend, "Canon", np.ones(1), marked_only=True, sort_by="filename_desc"
    )

    assert [match.path for match in results.matches] == [second, first]
    assert set(results.facet_paths) == {first, second}
    assert backend.search_filtered.call_args.args[1] == {first, second}


def test_hybrid_structured_filter_is_hard_for_both_branches(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    tagged = str(tmp_path / "tagged.jpg")
    untagged = str(tmp_path / "untagged.jpg")
    repo.upsert_image(tagged, "tagged.jpg", 1.0, 100, {"IPTC:Keywords": ["wildlife"]}, "Canon")
    repo.upsert_image(untagged, "untagged.jpg", 1.0, 100, {}, "Canon")
    repo.commit()
    backend = _vector_backend([(untagged, 0.9), (tagged, 0.8)])

    results = build_hybrid_results(
        repo, backend, 'Canon tags:="wildlife"', np.ones(1)
    )

    assert [match.path for match in results.matches] == [tagged]
    assert backend.search_filtered.call_args.args[1] == {tagged}


def test_hybrid_set_and_folder_scope_excludes_unrelated_semantic_hits(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    inside = _insert(repo, tmp_path / "chosen", "inside.jpg", "Nikon", 1609459200)
    outside = _insert(repo, tmp_path / "other", "outside.jpg", "Canon", 1609459200)
    not_in_set = _insert(repo, tmp_path / "chosen", "not-in-set.jpg", "Canon", 1609459200)
    repo.commit()
    set_id = repo.create_image_set("Selected")
    repo.add_images_to_set(set_id, [inside, outside])
    backend = _vector_backend([(outside, 0.99), (not_in_set, 0.95), (inside, 0.8)])

    results = build_hybrid_results(
        repo, backend, "Canon", np.ones(1),
        path_filter=[str(tmp_path / "chosen")], image_set_id=set_id,
    )

    assert [match.path for match in results.matches] == [inside]
    assert backend.search_filtered.call_args.args[1] == {inside}
    assert set(results.facet_paths) == {inside}


def test_hybrid_punctuation_only_discovery_does_not_match_all_metadata(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    matching = _insert(repo, tmp_path, "matching.jpg", "Canon", 1609459200)
    _insert(repo, tmp_path, "other.jpg", "Nikon", 1609459200)
    repo.commit()
    backend = _vector_backend([(matching, 0.9)])

    results = build_hybrid_results(repo, backend, "---", np.ones(1))

    assert [match.path for match in results.matches] == [matching]


def test_hybrid_strict_and_rejects_out_of_scope_backend_hits(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    matching = _insert(repo, tmp_path, "matching.jpg", "Canon", 1609459200)
    other = _insert(repo, tmp_path, "other.jpg", "Nikon", 1609459200)
    repo.commit()
    backend = Mock(spec=AiVectorBackend)
    backend.search_filtered.return_value = [(other, 0.9), (matching, 0.8)]

    results = build_hybrid_results(repo, backend, 'Canon ai:="deer"', np.ones(1))

    assert [match.path for match in results.matches] == [matching]


def test_hybrid_pools_duplicate_views_and_excludes_below_threshold(
    repo: ImageIndexRepository, tmp_path: Path
) -> None:
    matching = _insert(repo, tmp_path, "matching.jpg", "Nikon", 1609459200)
    below = _insert(repo, tmp_path, "below.jpg", "Nikon", 1609459200)
    repo.commit()
    backend = Mock(spec=AiVectorBackend)
    backend.search_filtered.return_value = [(matching, 0.3), (below, 0.1), (matching, 0.8)]

    results = build_hybrid_results(repo, backend, 'ai:="deer"', np.ones(1))

    assert len(results.matches) == 1
    assert results.matches[0].path == matching
    assert results.matches[0].ai_score == pytest.approx(0.8)
    assert results.total_count == 1
