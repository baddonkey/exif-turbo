#!/usr/bin/env python3
"""Build a reviewed visual-vocabulary manifest from a pinned Wikidata export."""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
from typing import Any


REQUIRED_LOCALES = ("en", "de", "fr", "it")
_QID_PATTERN = re.compile(r"^Q[1-9]\d*$")
_TGM_ID_PATTERN = re.compile(r"^(?:tgm)?(\d{6})$")
_NON_VISUAL_PATTERN = re.compile(
    r"\b(academic discipline|branch of science|legal concept|philosophical concept|"
    r"Wikimedia list|Wikimedia category|disambiguation page)\b",
    re.IGNORECASE,
)
_FORBIDDEN_INSTANCE_QIDS = {"Q4167410", "Q13406463", "Q4167836"}


class WikidataCurationError(RuntimeError):
    """The pinned curation inputs are invalid or inconsistent."""


def _qid_values(entity: dict[str, Any], property_id: str) -> tuple[str, ...]:
    claims = entity.get("claims", {})
    values: set[str] = set()
    if not isinstance(claims, dict):
        return ()
    statements = claims.get(property_id, [])
    if not isinstance(statements, list):
        return ()
    for statement in statements:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]["id"]
        except (KeyError, TypeError):
            continue
        if isinstance(value, str) and _QID_PATTERN.fullmatch(value):
            values.add(value)
    return tuple(sorted(values, key=lambda value: int(value[1:])))


def _external_id_values(
    entity: dict[str, Any], property_id: str
) -> tuple[str, ...]:
    claims = entity.get("claims", {})
    values: set[str] = set()
    if not isinstance(claims, dict):
        return ()
    statements = claims.get(property_id, [])
    if not isinstance(statements, list):
        return ()
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("rank") == "deprecated":
            continue
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
        except (KeyError, TypeError):
            continue
        match = _TGM_ID_PATTERN.fullmatch(value) if isinstance(value, str) else None
        if match is not None:
            values.add(f"tgm{match.group(1)}")
    return tuple(sorted(values))


def _localized_value(entity: dict[str, Any], field: str, locale: str) -> str:
    values = entity.get(field, {})
    if not isinstance(values, dict):
        return ""
    value = values.get(locale, {})
    return str(value.get("value", "")).strip() if isinstance(value, dict) else ""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WikidataCurationError(f"{path.name} must contain a JSON object")
    return value


def _load_entities(path: Path) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise WikidataCurationError(
                    f"invalid entity on line {line_number} of {path.name}"
                )
            qid = value["id"]
            if not _QID_PATTERN.fullmatch(qid) or qid in entities:
                raise WikidataCurationError(f"invalid or duplicate entity ID: {qid}")
            entities[qid] = value
    return entities


class WikidataVocabularyCurator:
    """Select reproducible visual candidates from an offline entity graph."""

    def curate(
        self,
        roots_path: Path,
        overrides_path: Path,
        entities_path: Path,
        manifest_path: Path,
        review_path: Path,
        discovery_path: Path | None = None,
        tgm_discovery_path: Path | None = None,
    ) -> dict[str, Any]:
        roots = _load_json(roots_path)
        overrides = _load_json(overrides_path)
        entities = _load_entities(entities_path)
        self._validate_inputs(roots, overrides)
        include_assignments = self._load_include_assignments(
            overrides,
            roots["domains"],
        )
        forced_includes = set(overrides.get("include", [])).union(
            include_assignments
        )
        forced_excludes = set(overrides.get("exclude", []))
        assignments = self._assign_domains(roots["domains"], entities)
        broad_discovery_qids: set[str] = set()
        if discovery_path is not None:
            broad_assignments = self._load_discovery_assignments(
                discovery_path,
                roots["domains"],
                entities,
                snapshot_version=int(roots["snapshot_version"]),
            )
            broad_discovery_qids = set(broad_assignments)
            assignments.update(broad_assignments)
        if tgm_discovery_path is not None:
            tgm_assignments = self._load_discovery_assignments(
                tgm_discovery_path,
                roots["domains"],
                entities,
                snapshot_version=int(roots["snapshot_version"]),
                property_id="P5160",
                roots_sha256=hashlib.sha256(roots_path.read_bytes()).hexdigest(),
            )
            for qid, (domain, category, depth, priority) in tgm_assignments.items():
                if qid not in broad_discovery_qids:
                    assignments[qid] = (
                        domain,
                        category,
                        depth,
                        1_000_000_000 + priority,
                    )
        assignments.update(include_assignments)
        self._validate_overrides(
            forced_includes,
            forced_excludes,
            entities,
            assignments,
        )
        rows = self._candidate_rows(
            assignments,
            entities,
            forced_includes,
            forced_excludes,
        )
        self._validate_forced_includes(rows, forced_includes)
        domain_counts = self._apply_domain_quotas(
            rows,
            roots["domains"],
            forced_includes,
        )
        self._rebalance_domain_shortfalls(
            rows,
            roots["domains"],
            int(roots["target_count"]),
        )
        self._mark_collisions(rows, forced_includes)
        self._refill_after_collisions(
            rows,
            roots["domains"],
            int(roots["target_count"]),
        )
        self._append_tgm_overflow(rows)
        self._update_domain_counts(domain_counts, rows)
        selected = [row for row in rows if row["status"] == "included"]
        selected.sort(key=lambda row: int(row["qid"][1:]))
        manifest = {
            "schema_version": 1,
            "snapshot_version": int(roots["snapshot_version"]),
            "created_at": str(roots["created_at"]),
            "source": {
                "name": "Wikidata",
                "dump_uri": str(roots["source_dump_uri"]),
                "dump_sha256": hashlib.sha256(entities_path.read_bytes()).hexdigest(),
                "license_id": "CC0-1.0",
            },
            "concepts": [
                {"qid": row["qid"], "category": row["category"]}
                for row in selected
            ],
        }
        review = {
            "schema_version": 1,
            "target_count": int(roots["target_count"]),
            "selected_count": len(selected),
            "target_shortfall": max(0, int(roots["target_count"]) - len(selected)),
            "selected_overflow": max(0, len(selected) - int(roots["target_count"])),
            "domain_counts": domain_counts,
            "source_sha256": manifest["source"]["dump_sha256"],
            "rows": rows,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        review_path.write_text(
            json.dumps(review, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return review

    @staticmethod
    def _validate_inputs(roots: dict[str, Any], overrides: dict[str, Any]) -> None:
        if roots.get("schema_version") != 1 or not isinstance(roots.get("domains"), list):
            raise WikidataCurationError("unsupported visual-domain roots schema")
        target_count = roots.get("target_count")
        domains = roots["domains"]
        if (
            isinstance(target_count, bool)
            or not isinstance(target_count, int)
            or target_count < 1
            or not all(
                isinstance(domain, dict)
                and isinstance(domain.get("target_count"), int)
                and not isinstance(domain.get("target_count"), bool)
                and domain["target_count"] >= 0
                for domain in domains
            )
            or sum(domain["target_count"] for domain in domains) != target_count
        ):
            raise WikidataCurationError(
                "domain target counts must be non-negative and sum to target_count"
            )
        if overrides.get("schema_version") != 1:
            raise WikidataCurationError("unsupported curation overrides schema")
        for key in ("include", "exclude"):
            values = overrides.get(key, [])
            if not isinstance(values, list) or not all(
                isinstance(value, str) and _QID_PATTERN.fullmatch(value)
                for value in values
            ):
                raise WikidataCurationError(f"override {key} must contain QIDs")
        overlap = set(overrides.get("include", [])).intersection(
            overrides.get("exclude", [])
        )
        if overlap:
            raise WikidataCurationError("include and exclude overrides overlap")

    @staticmethod
    def _load_include_assignments(
        overrides: dict[str, Any],
        domains: list[dict[str, Any]],
    ) -> dict[str, tuple[str, str, int, int]]:
        values = overrides.get("include_assignments", [])
        if not isinstance(values, list):
            raise WikidataCurationError("include_assignments must be an array")
        configured = {
            str(domain["name"]): str(domain["category"])
            for domain in domains
        }
        assignments: dict[str, tuple[str, str, int, int]] = {}
        for value in values:
            if not isinstance(value, dict):
                raise WikidataCurationError(
                    "include_assignments entries must be objects"
                )
            qid = value.get("qid")
            domain = value.get("domain")
            category = value.get("category")
            if (
                not isinstance(qid, str)
                or not _QID_PATTERN.fullmatch(qid)
                or not isinstance(domain, str)
                or configured.get(domain) != category
                or qid in assignments
            ):
                raise WikidataCurationError("invalid include assignment")
            assignments[qid] = (domain, str(category), 0, 0)
        overlap = set(overrides.get("include", [])).intersection(assignments)
        if overlap:
            raise WikidataCurationError(
                "include and include_assignments overrides overlap"
            )
        return assignments

    @staticmethod
    def _assign_domains(
        domains: list[dict[str, Any]],
        entities: dict[str, dict[str, Any]],
    ) -> dict[str, tuple[str, str, int, int]]:
        children: dict[str, list[str]] = {}
        for qid, entity in entities.items():
            for parent in _qid_values(entity, "P279"):
                children.setdefault(parent, []).append(qid)
        assignments: dict[str, tuple[str, str, int, int]] = {}
        for domain in domains:
            name = str(domain["name"])
            category = str(domain["category"])
            max_depth = int(domain["max_depth"])
            queue = deque(
                (str(root_qid), 0) for root_qid in domain.get("root_qids", [])
            )
            seen: set[str] = set()
            while queue:
                qid, depth = queue.popleft()
                if qid in seen or depth > max_depth:
                    continue
                seen.add(qid)
                if qid in entities and qid not in assignments:
                    assignments[qid] = (name, category, depth, int(qid[1:]))
                for child in sorted(
                    children.get(qid, []), key=lambda value: int(value[1:])
                ):
                    queue.append((child, depth + 1))
        return assignments

    @staticmethod
    def _load_discovery_assignments(
        path: Path,
        domains: list[dict[str, Any]],
        entities: dict[str, dict[str, Any]],
        *,
        snapshot_version: int,
        property_id: str | None = None,
        roots_sha256: str | None = None,
    ) -> dict[str, tuple[str, str, int, int]]:
        document = _load_json(path)
        concepts = document.get("concepts")
        if document.get("schema_version") != 1 or not isinstance(concepts, list):
            raise WikidataCurationError("unsupported discovery schema")
        configured = {
            str(domain["name"]): str(domain["category"])
            for domain in domains
        }
        if document.get("snapshot_version") != snapshot_version:
            raise WikidataCurationError("discovery snapshot version mismatch")
        if property_id is None:
            completed_domains = document.get("completed_domains")
            if (
                not isinstance(completed_domains, list)
                or set(completed_domains) != set(configured)
            ):
                raise WikidataCurationError("broad discovery is incomplete")
        elif (
            document.get("complete") is not True
            or document.get("property_id") != property_id
            or document.get("roots_sha256") != roots_sha256
        ):
            raise WikidataCurationError("TGM discovery is incomplete or mismatched")
        if property_id is not None:
            items = document.get("items")
            discovered_assignments = document.get("assignments")
            unmapped_qids = document.get("unmapped_qids")
            if (
                document.get("enumeration_complete") is not True
                or not isinstance(items, dict)
                or not isinstance(discovered_assignments, dict)
                or not isinstance(unmapped_qids, list)
                or document.get("classification_offset") != len(items)
                or any(
                    not isinstance(qid, str)
                    or not _QID_PATTERN.fullmatch(qid)
                    or isinstance(popularity, bool)
                    or not isinstance(popularity, int)
                    or popularity < 0
                    for qid, popularity in items.items()
                )
                or any(
                    not isinstance(qid, str)
                    or not _QID_PATTERN.fullmatch(qid)
                    or not isinstance(assignment, dict)
                    or not isinstance(assignment.get("domain"), str)
                    or configured.get(assignment.get("domain"))
                    != assignment.get("category")
                    for qid, assignment in discovered_assignments.items()
                )
                or any(
                    not isinstance(qid, str) or not _QID_PATTERN.fullmatch(qid)
                    for qid in unmapped_qids
                )
                or len(unmapped_qids) != len(set(unmapped_qids))
                or set(discovered_assignments).intersection(unmapped_qids)
                or set(discovered_assignments).union(unmapped_qids) != set(items)
            ):
                raise WikidataCurationError("inconsistent TGM discovery checkpoint")
        assignments: dict[str, tuple[str, str, int, int]] = {}
        for concept in concepts:
            if not isinstance(concept, dict):
                raise WikidataCurationError("discovery concepts must be objects")
            qid = concept.get("qid")
            domain = concept.get("domain")
            category = concept.get("category")
            priority = concept.get("priority")
            if (
                not isinstance(qid, str)
                or not _QID_PATTERN.fullmatch(qid)
                or qid not in entities
                or not isinstance(domain, str)
                or configured.get(domain) != category
                or isinstance(priority, bool)
                or not isinstance(priority, int)
                or priority < 1
                or qid in assignments
            ):
                raise WikidataCurationError("invalid discovery assignment")
            assignments[qid] = (domain, str(category), 0, priority)
        if property_id is not None:
            if set(assignments) != set(discovered_assignments):
                raise WikidataCurationError("inconsistent TGM discovery concepts")
            expected_priority: dict[str, int] = {}
            priority_by_domain: dict[str, int] = {}
            for qid in sorted(
                discovered_assignments,
                key=lambda value: (-int(items[value]), int(value[1:])),
            ):
                domain = str(discovered_assignments[qid]["domain"])
                priority_by_domain[domain] = priority_by_domain.get(domain, 0) + 1
                expected_priority[qid] = priority_by_domain[domain]
            for concept in concepts:
                qid = str(concept["qid"])
                assignment = discovered_assignments[qid]
                popularity = concept.get("popularity")
                if (
                    concept.get("domain") != assignment.get("domain")
                    or concept.get("category") != assignment.get("category")
                    or isinstance(popularity, bool)
                    or not isinstance(popularity, int)
                    or popularity != items[qid]
                    or concept.get("priority") != expected_priority[qid]
                ):
                    raise WikidataCurationError(
                        "inconsistent TGM discovery concepts"
                    )
                if not _external_id_values(entities[qid], property_id):
                    raise WikidataCurationError(
                        f"TGM discovery QID lacks a current {property_id} claim: {qid}"
                    )
        return assignments

    @staticmethod
    def _validate_overrides(
        forced_includes: set[str],
        forced_excludes: set[str],
        entities: dict[str, dict[str, Any]],
        assignments: dict[str, tuple[str, str, int, int]],
    ) -> None:
        unknown = (forced_includes | forced_excludes).difference(entities)
        if unknown:
            raise WikidataCurationError(
                f"override QIDs are missing from the entity source: {sorted(unknown)}"
            )
        unassigned = forced_includes.difference(assignments)
        if unassigned:
            raise WikidataCurationError(
                f"included QIDs are outside configured domains: {sorted(unassigned)}"
            )

    @staticmethod
    def _candidate_rows(
        assignments: dict[str, tuple[str, str, int]],
        entities: dict[str, dict[str, Any]],
        forced_includes: set[str],
        forced_excludes: set[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for qid, (domain, category, depth, priority) in assignments.items():
            entity = entities[qid]
            tgm_ids = sorted(_external_id_values(entity, "P5160"))
            labels = {
                locale: _localized_value(entity, "labels", locale)
                for locale in REQUIRED_LOCALES
            }
            reasons: list[str] = []
            if any(not label for label in labels.values()):
                reasons.append("missing_required_locale")
            if _FORBIDDEN_INSTANCE_QIDS.intersection(_qid_values(entity, "P31")):
                reasons.append("forbidden_entity_class")
            description = _localized_value(entity, "descriptions", "en")
            if _NON_VISUAL_PATTERN.search(description):
                reasons.append("non_visual_description")
            if qid in forced_excludes:
                reasons.append("explicitly_excluded")
            status = "included" if not reasons else "excluded"
            if qid in forced_includes and "missing_required_locale" not in reasons:
                status = "included"
                reasons = ["explicitly_included"]
            rows.append(
                {
                    "qid": qid,
                    "domain": domain,
                    "category": category,
                    "depth": depth,
                    "priority": priority,
                    "labels": labels,
                    "description_en": description,
                    "tgm_ids": tgm_ids,
                    "status": status,
                    "reasons": reasons,
                    "collisions": [],
                }
            )
        rows.sort(key=lambda row: (row["domain"], row["depth"], int(row["qid"][1:])))
        return rows

    @staticmethod
    def _validate_forced_includes(
        rows: list[dict[str, Any]],
        forced_includes: set[str],
    ) -> None:
        ineligible = [
            row["qid"]
            for row in rows
            if row["qid"] in forced_includes and row["status"] != "included"
        ]
        if ineligible:
            raise WikidataCurationError(
                f"forced includes fail required quality gates: {sorted(ineligible)}"
            )

    @staticmethod
    def _mark_collisions(rows: list[dict[str, Any]], forced_includes: set[str]) -> None:
        labels: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            if row["status"] != "included" and row["reasons"] != ["domain_quota"]:
                continue
            for locale, label in row["labels"].items():
                labels.setdefault((locale, label.casefold()), []).append(row)
        for candidates in labels.values():
            if len(candidates) < 2:
                continue
            qids = sorted(row["qid"] for row in candidates)
            for row in candidates:
                row["collisions"] = sorted(
                    set(row["collisions"]).union(qids).difference({row["qid"]})
                )

        claimed_labels: set[tuple[str, str]] = set()
        included = sorted(
            (row for row in rows if row["status"] == "included"),
            key=lambda row: (
                row["qid"] not in forced_includes,
                row["priority"],
                row["depth"],
                int(row["qid"][1:]),
            ),
        )
        for row in included:
            keys = {
                (locale, label.casefold())
                for locale, label in row["labels"].items()
            }
            if keys.intersection(claimed_labels) and row["qid"] in forced_includes:
                raise WikidataCurationError(
                    "forced includes have conflicting localized labels"
                )
            if keys.intersection(claimed_labels):
                row["status"] = "excluded"
                row["reasons"] = ["label_collision"]
                continue
            claimed_labels.update(keys)

    @staticmethod
    def _apply_domain_quotas(
        rows: list[dict[str, Any]],
        domains: list[dict[str, Any]],
        forced_includes: set[str],
    ) -> list[dict[str, int | str]]:
        counts: list[dict[str, int | str]] = []
        for domain in domains:
            name = str(domain["name"])
            target = int(domain["target_count"])
            eligible = [
                row
                for row in rows
                if row["domain"] == name and row["status"] == "included"
            ]
            forced_count = sum(
                row["qid"] in forced_includes for row in eligible
            )
            if forced_count > target:
                raise WikidataCurationError(
                    f"domain {name} has {forced_count} forced includes for quota {target}"
                )
            eligible.sort(
                key=lambda row: (
                    row["qid"] not in forced_includes,
                    row["priority"],
                    row["depth"],
                    int(row["qid"][1:]),
                )
            )
            for row in eligible[target:]:
                row["status"] = "excluded"
                row["reasons"] = ["domain_quota"]
            selected_count = min(len(eligible), target)
            counts.append(
                {
                    "domain": name,
                    "target_count": target,
                    "eligible_count": len(eligible),
                    "selected_count": selected_count,
                    "shortfall": target - selected_count,
                }
            )
        return counts

    @staticmethod
    def _rebalance_domain_shortfalls(
        rows: list[dict[str, Any]],
        domains: list[dict[str, Any]],
        target_count: int,
    ) -> None:
        selected_count = sum(row["status"] == "included" for row in rows)
        needed = target_count - selected_count
        if needed <= 0:
            return
        targets = {
            str(domain["name"]): int(domain["target_count"])
            for domain in domains
        }
        overflow_candidates = [
            row
            for row in rows
            if row["status"] == "excluded" and row["reasons"] == ["domain_quota"]
        ]
        overflow_candidates.sort(
            key=lambda row: (
                row["priority"] / max(1, targets[row["domain"]]),
                row["priority"],
                int(row["qid"][1:]),
            )
        )
        for row in overflow_candidates[:needed]:
            row["status"] = "included"
            row["reasons"] = ["quota_rebalanced"]

    @staticmethod
    def _refill_after_collisions(
        rows: list[dict[str, Any]],
        domains: list[dict[str, Any]],
        target_count: int,
    ) -> None:
        needed = target_count - sum(row["status"] == "included" for row in rows)
        if needed <= 0:
            return
        targets = {
            str(domain["name"]): int(domain["target_count"])
            for domain in domains
        }
        claimed_labels = {
            (locale, label.casefold())
            for row in rows
            if row["status"] == "included"
            for locale, label in row["labels"].items()
        }
        candidates = [
            row
            for row in rows
            if row["status"] == "excluded" and row["reasons"] == ["domain_quota"]
        ]
        candidates.sort(
            key=lambda row: (
                row["priority"] / max(1, targets[row["domain"]]),
                row["priority"],
                int(row["qid"][1:]),
            )
        )
        for row in candidates:
            keys = {
                (locale, label.casefold())
                for locale, label in row["labels"].items()
            }
            if keys.intersection(claimed_labels):
                continue
            row["status"] = "included"
            row["reasons"] = ["quota_rebalanced"]
            claimed_labels.update(keys)
            needed -= 1
            if needed == 0:
                break

    @staticmethod
    def _append_tgm_overflow(rows: list[dict[str, Any]]) -> None:
        rows_by_qid = {row["qid"]: row for row in rows}
        claimed_labels = {
            (locale, label.casefold()): row["qid"]
            for row in rows
            if row["status"] == "included"
            for locale, label in row["labels"].items()
        }
        candidates = sorted(
            (
                row
                for row in rows
                if row["status"] == "excluded"
                and row["reasons"] == ["domain_quota"]
                and row["tgm_ids"]
            ),
            key=lambda row: (
                row["priority"],
                row["depth"],
                int(row["qid"][1:]),
            ),
        )
        collision_groups: dict[tuple[str, str], set[str]] = {}
        for row in [
            *(row for row in rows if row["status"] == "included"),
            *candidates,
        ]:
            for locale, label in row["labels"].items():
                collision_groups.setdefault(
                    (locale, label.casefold()), set()
                ).add(row["qid"])
        for qids in collision_groups.values():
            if len(qids) < 2:
                continue
            for qid in qids:
                row = rows_by_qid[qid]
                row["collisions"] = sorted(
                    set(row["collisions"]).union(qids).difference({qid})
                )
        for row in candidates:
            keys = {
                (locale, label.casefold())
                for locale, label in row["labels"].items()
            }
            colliding_qids = {
                claimed_labels[key]
                for key in keys.intersection(claimed_labels)
            }
            if colliding_qids:
                row["reasons"] = ["label_collision"]
                continue
            row["status"] = "included"
            row["reasons"] = ["tgm_priority"]
            claimed_labels.update((key, row["qid"]) for key in keys)

    @staticmethod
    def _update_domain_counts(
        counts: list[dict[str, int | str]],
        rows: list[dict[str, Any]],
    ) -> None:
        selected_by_domain = {
            str(count["domain"]): sum(
                row["status"] == "included"
                and row["domain"] == count["domain"]
                for row in rows
            )
            for count in counts
        }
        for count in counts:
            selected_count = selected_by_domain[str(count["domain"])]
            target_count = int(count["target_count"])
            count["selected_count"] = selected_count
            count["shortfall"] = max(0, target_count - selected_count)
            count["overflow"] = max(0, selected_count - target_count)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path)
    parser.add_argument("overrides", type=Path)
    parser.add_argument("entities", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--discovery", type=Path)
    parser.add_argument("--tgm-discovery", type=Path)
    arguments = parser.parse_args()
    WikidataVocabularyCurator().curate(
        arguments.roots,
        arguments.overrides,
        arguments.entities,
        arguments.manifest,
        arguments.review,
        arguments.discovery,
        arguments.tgm_discovery,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())