# Wikidata vocabulary source

`vocabulary-manifest.example.json` is a small curator example, not a production
manifest. Its all-zero SHA256 is intentionally invalid for real input.
`vocabulary-manifest-v2.json` and `wikidata-visual-entities-v2.jsonl` are the
auto-reviewed, pinned inputs for the bundled 8,313-concept version 2
vocabulary. The configured 8,200-concept base is preserved while qualified
Wikidata concepts carrying the Library of Congress TGM identifier (`P5160`)
may be appended. `wikidata-review-v2.json` records every inclusion, exclusion,
collision, domain shortfall, rebalanced quota decision, and TGM-priority
addition. The version 1 files retain the original 80-concept release inputs.

The production runtime snapshot is checked in at
`src/exif_turbo/assets/wikidata-vocabulary-v2.json.gz`. Wikidata access is a
curator/release operation only; the application never calls the API at runtime.
The 250+ MiB production entity export is stored through Git LFS. After a fresh
clone, run `git lfs pull` before curation or byte-identical artifact tests.

## Curator workflow

1. Discover a broad candidate pool from the configured visual-domain roots.
The checkpoint is resumable and records each candidate's domain and priority:

```text
python scripts/discover_wikidata_visual_candidates.py \
  assets/wikidata/visual-domain-roots.json \
  assets/wikidata/wikidata-discovery-v2.json \
  --candidate-multiplier 2
```

2. Discover all `P5160`-linked Wikidata items and classify visual candidates
against the configured domains. Classification follows subclass, instance,
and taxon ancestry. Unmapped items remain in the checkpoint for audit and are
not assigned a guessed domain:

```text
python scripts/discover_wikidata_tgm_candidates.py \
  assets/wikidata/visual-domain-roots.json \
  assets/wikidata/wikidata-tgm-discovery-v2.json
```

3. Pin all discovered entities, including the claims used by graph-based
quality gates:

```text
python scripts/fetch_wikidata_entities.py \
  --manifest assets/wikidata/wikidata-discovery-v2.json \
  --output assets/wikidata/wikidata-visual-entities-v2.jsonl \
  --include-claims
```

The fetcher calls the official MediaWiki `wbgetentities` API in deterministic
batches and requests labels, aliases, and descriptions for `en`, `de`, `fr`,
and `it`. `--api-url` can override the official endpoint for controlled
testing.

When TGM discovery adds mapped QIDs, fetch only entities absent from the pinned
source and merge the sorted exports atomically:

```text
python scripts/fetch_wikidata_entities.py \
  --manifest assets/wikidata/wikidata-tgm-discovery-v2.json \
  --output assets/wikidata/wikidata-tgm-supplement.jsonl \
  --exclude-entities assets/wikidata/wikidata-visual-entities-v2.jsonl \
  --include-claims
python scripts/merge_wikidata_entities.py \
  assets/wikidata/wikidata-visual-entities-v2.jsonl \
  assets/wikidata/wikidata-tgm-supplement.jsonl \
  --output assets/wikidata/wikidata-visual-entities-v2.jsonl
```

4. Apply hard quality gates, explicit overrides, localized-label collision
resolution, domain quotas, and global quota rebalancing. The curator writes
both the selected manifest and a complete decision audit. TGM-linked concepts
that pass every gate but exceed a domain quota are appended above the 8,200
base rather than displacing it:

```text
python scripts/curate_wikidata_vocabulary.py \
  assets/wikidata/visual-domain-roots.json \
  assets/wikidata/curation-overrides.json \
  assets/wikidata/wikidata-visual-entities-v2.jsonl \
  assets/wikidata/vocabulary-manifest-v2.json \
  assets/wikidata/wikidata-review-v2.json \
  --discovery assets/wikidata/wikidata-discovery-v2.json \
  --tgm-discovery assets/wikidata/wikidata-tgm-discovery-v2.json
```

5. Generate the runtime snapshot from the auto-reviewed, checksummed local
files:

```text
python scripts/generate_wikidata_snapshot.py \
  --manifest assets/wikidata/vocabulary-manifest-v2.json \
  --dump assets/wikidata/wikidata-visual-entities-v2.jsonl \
  --output src/exif_turbo/assets/wikidata-vocabulary-v2.json.gz
```

The generator uses only local files and performs no API or WDQS requests. The
selected Wikidata labels and aliases are recorded as `CC0-1.0`. Generation fails
when the dump checksum differs, a selected QID is missing or deleted, or any
selected concept lacks `en`, `de`, `fr`, or `it` labels.

## Public-figure identity workflow

Named people are curated separately from the visual-concept vocabulary. The
version 1 criteria select prominent politicians, monarchs, entertainers,
athletes, artists, writers, scientists, and business leaders who were alive at
some point since 1826 and have a Commons portrait plus `en`, `de`, `fr`, and
`it` labels. Per-group targets total 10,500 before identities belonging to
multiple groups are deduplicated:

```text
python scripts/discover_wikidata_public_figures.py \
  assets/wikidata/public-figure-criteria-v1.json \
  assets/wikidata/wikidata-public-figures-v1.json
```

The resulting schema-v1 document is directly consumable by the existing entity
fetcher. Keep the identity export separate from the visual entity export:

```text
python scripts/fetch_wikidata_entities.py \
  --manifest assets/wikidata/wikidata-public-figures-v1.json \
  --output assets/wikidata/wikidata-public-figure-entities-v1.jsonl
```

Discovery records one Wikidata `P18` portrait reference per identity for audit
and later reference-image acquisition. Each identity retains every matching
group so clients can expose category filters. Discovery does not perform face
recognition or download Commons media at application runtime.

Convert the completed discovery plus pinned entities into the standard,
checksummed manifest format and generate the bundled runtime snapshot:

```text
python scripts/prepare_wikidata_public_figure_manifest.py \
  assets/wikidata/wikidata-public-figures-v1.json \
  assets/wikidata/wikidata-public-figure-entities-v1.jsonl \
  assets/wikidata/public-figure-manifest-v1.json
python scripts/generate_wikidata_snapshot.py \
  --manifest assets/wikidata/public-figure-manifest-v1.json \
  --dump assets/wikidata/wikidata-public-figure-entities-v1.jsonl \
  --output src/exif_turbo/assets/wikidata-public-figures-v1.json.gz
```

At runtime, public figures use a separate FAISS index built from multilingual
name and alias prompts. Their hits are merged with visual-concept proposals,
but remain review-only and are never auto-accepted. This is CLIP name matching,
not biometric face recognition. When the optional bundled identity snapshot is
absent, visual-concept proposals continue to operate unchanged.