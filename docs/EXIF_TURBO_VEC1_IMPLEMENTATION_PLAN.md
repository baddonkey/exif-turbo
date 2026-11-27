# exif-turbo: migrate FAISS to SQLite Vec1 and implement hybrid search

**Developer handoff / VS Code GitHub Copilot Agent Mode**  
Repository: https://github.com/baddonkey/exif-turbo  
Decision: use SQLite Vec1 as the vector engine; keep CLIP and the existing SQLCipher metadata database.  
Reference baseline: main branch documentation for v1.23.2 (reviewed 25 November 2026). Verify the actual checkout before coding.

## Copilot task

Implement this plan in small, reviewable changes with tests. Start by mapping the current implementation and recording actual file paths, schema and APIs; do not assume the example names below exist. Read repository instructions, project specifications and the user manual. Preserve current metadata and AI search behaviour, encryption, settings, image sets, UI responsiveness and cross-platform distribution. Use the existing project conventions and worker lifecycle. Complete the feasibility phase first; if Vec1 cannot be loaded safely on a supported SQLCipher build, report the precise build issue and preserve the existing working backend rather than bypassing encryption. Do not implement a new database service or require a Java runtime. Do not change the CLIP model just to enable this migration.

## 1. Goal and non-goals

- Store image embeddings and the Vec1 index in the same SQLCipher database as metadata and FTS5. In production, no separate FAISS index should be needed after a verified migration.
- Preserve metadata-only and AI-only modes; add a Hybrid mode using both engines in one result list.
- Keep results stable across infinite scrolling and enforce date, folder, format, set and metadata restrictions before candidate limits.
- Preserve local-first operation, existing password protection, cancellation, incremental/full scans and per-database configuration.
- Non-goals: cloud inference, new embedding models, automatic tag writing, new external vector service, arbitrary Boolean expressions mixing multiple AI clauses in the first release.

## 2. Phase A — audit and feasibility spike

- [ ] Locate the database connection factory, SQLCipher version/build options, schema migrations, FTS5 parser/repository, CLIP model configuration, FAISS worker, encrypted snapshot reader/writer, image ID/path mapping and multi-view pooling logic.
- [ ] Locate search controller/QML, paging/sorting and facet/timeline queries, saved set filters, scan queue, cancellation, settings/i18n and platform packaging/CI.
- [ ] Document exact existing FAISS metric, vector normalization, dimension, model identity, threshold semantics, embedding views and index reconstruction support. Never assume 512 dimensions or one vector per image.
- [ ] Pin an official Vec1 source version and checksum, record its license and release status. Test the current documented API against the pinned code. Vec1 is currently a pre-1.0 extension; avoid relying on undocumented features.
- [ ] Build/load the extension using the same SQLCipher connection used by the application. Verify `SELECT vec1_info()` and create, insert, query, delete, reopen an encrypted test database using the existing Python driver.
- [ ] Exercise all supported release targets and CPU paths; verify AVX2 availability or supported fallback on x86, NEON/ARM builds, macOS signing and frozen application loading. Do not assume the extension can load on a different SQLite ABI.
- [ ] Record the dependency, build process, expected performance and limitations in an ADR or equivalent repository document.

**Exit gate:** Working encrypted persistence, reproducible native builds and correct vector-distance results on supported targets; unsupported AI environments still start and support metadata search. Do not remove FAISS yet.

## 3. Phase B — data model and repository

Use a normal mapping table and a Vec1 virtual table. Names and SQL are illustrative; adapt to the actual schema and pinned Vec1 API.

```sql
CREATE TABLE image_embedding_map (
    vector_id INTEGER PRIMARY KEY,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    view_key TEXT NOT NULL,
    UNIQUE (image_id, view_key)
);
CREATE VIRTUAL TABLE image_vectors USING vec1(embedding);
```

`image_vectors.rowid` equals `image_embedding_map.vector_id`. Prefer one active model generation per named database; record model identifier, weights/version, dimension, preprocessing/view strategy, normalization, distance metric, vector byte order, Vec1 version, trained-index parameters and schema generation in a regular SQLCipher table. Use a generation/staging strategy for incompatible model changes. No redundant ordinary BLOB copy unless justified by benchmarks or a rebuild requirement. Confirm Vec1 supports retrieving original vectors from its own table when training/reranking.

- [ ] Store finite, non-zero float32 vectors in Vec1's native BLOB format; validate dimension and byte order. Preserve the current CLIP preprocessing and all view identities.
- [ ] Allocate vector IDs transactionally and update mapping and virtual table together. Implement insert/replace/delete explicitly using supported Vec1 APIs; do not assume virtual tables support foreign keys, UPSERT or cascades. Route image and folder removals through repository code or verified trigger strategy. Test rollback/orphan cleanup.
- [ ] Implement backend abstraction (existing FAISS and new Vec1 during transition) with operations for upsert views, delete images, exact search, indexed retrieval, rebuild/status, and close.
- [ ] Keep model load and query encoding local and lazy; no Vec1 requirement for metadata-only operations when AI is unavailable.
- [ ] Use existing database migration framework and connections; ensure extension registration on every connection that accesses vector tables. Load only the bundled, verified extension; disable further arbitrary extension loading after registration when supported.

### Encryption requirements

All persistent vectors, Vec1 shadow tables, trained model parameters and mapping data must reside inside the same encrypted SQLCipher database. Check actual shadow-table storage and any files generated by training. Use existing key management; do not create an unencrypted sidecar or a second password. Keep sensitive working data in memory where practical; explicitly configure and verify temporary storage behaviour (including sort spill and worker jobs). Never log embedding bytes or plaintext paths added by this feature. Verify encrypted WAL, backup/restore, reopen, wrong-password rejection and absence of plaintext artifacts. Passwordless development databases retain their existing explicitly unencrypted behaviour; memory is not encrypted by SQLCipher. Keep extension loading restricted to trusted local binaries.

**Exit gate:** CRUD, rollback, deletion, reopening and encryption tests pass; original metadata search continues to work.

## 4. Phase C — exact baseline and indexed Vec1 search

Build exact retrieval first so there is a correctness oracle for ANN. If the existing AI metric is normalized cosine similarity, convert distance with `score = 1 - cosine_distance`. Verify against FAISS before reusing thresholds. Current manual documents Broad 0.18, Normal 0.20 and Fine 0.22 similarity thresholds. Preserve the effective multi-view behaviour (verify pooling in code).

Example exact scoring with hard scope already materialized as unique eligible image IDs:

```sql
WITH image_scores AS (
    SELECT m.image_id,
           MIN(vec1_cos_distance(v.embedding, :query_vector)) AS distance
    FROM eligible_images AS e
    JOIN image_embedding_map AS m ON m.image_id = e.image_id
    JOIN image_vectors AS v ON v.rowid = m.vector_id
    GROUP BY m.image_id
)
SELECT image_id, 1.0 - distance AS ai_score
FROM image_scores
WHERE distance <= 1.0 - :min_similarity
ORDER BY distance, image_id;
```

This example assumes best-view cosine pooling; implement the actual current pooling rule if different. Use `EXPLAIN QUERY PLAN` and benchmarks to verify selective scopes efficiently join to vector rows. If needed, fetch BLOBs by row ID in batches and use exact native scoring. This is an exhaustive query, not ANN. Do not recompute it per UI page.

### ANN optimization

- [ ] Train Vec1's index using representative embeddings via `vec1_train` and rebuild with the documented `INSERT ... (cmd,arg) VALUES ('rebuild', :model)` API. Use cosine configuration if verified equivalent. Evaluate bucket count, quantizer/code size, probe settings, CPU threads, training time and minimum sample requirements. Do not hard-code a large training configuration for every collection size.
- [ ] For selective, arbitrary FTS/set/metadata scopes use exact scoped scoring initially; for large scopes test Vec1 filtered streaming retrieval or metadata pushdown for simple scope fields, using the pinned API.
- [ ] Exact-rerank approximate candidates and pool per image before applying threshold and display cap. Overfetch adaptively for multiple views and selective restrictions; never retrieve a global 2,000 vectors and discard out-of-scope rows afterwards. Multiple views must not consume multiple image-result slots.
- [ ] Keep an exact fallback for strict threshold-complete counts, very selective filters, missing/untrained index, and unsuitable ANN recall. Approximate candidates cannot guarantee exhaustive matches or exact histogram counts; do not silently change documented behaviour.
- [ ] Train/retrain in background; handle updates, cancellation and failed rebuild transactionally. Check whether pinned Vec1 supports incremental inserts/deletes against a trained index and when retraining is useful. Keep the last valid index usable if feasible; otherwise surface clear progress and fallback.

**Exit gate:** Exact results match the legacy engine within tolerance; ANN recall and latency meet the measured acceptance targets in section 9, or exact search remains default until they do.

## 5. Phase D — unified hybrid query semantics

Add a third mode alongside existing modes, with metadata/visual input fields or a compact unified box. Preserve existing EXIF/metadata parser and the current AI query entry. Suggested explicit operator: `ai:="red deer in snow"`. A first release only needs one positive AI clause.

| Query / mode | Expected behaviour |
| --- | --- |
| Metadata: `Canon OR Nikon` | Unchanged FTS5/structured behaviour |
| AI: `red deer in snow` | Unchanged semantic retrieval and precision thresholds |
| Hybrid: `red deer in snow` | Discovery: metadata OR semantic matches, deduplicated |
| Hybrid: `Canon ai:="red deer in snow"` | Explicit AND: Canon metadata required, AI threshold required |
| Hybrid: `tags:="wildlife" ai:="forest"` | Exact tag required; semantic ranking inside scope |
| Hybrid with empty input | Same browse-all-in-scope behaviour |

Structured filters, selected folders/formats/dates/sets, enabled-folder status and marked-only filter are hard constraints, not relevance hints. Discovery searches must not accidentally apply unqualified terms as a hard filter to the semantic branch. Do not silently broaden explicit AND queries if AI is unavailable; explain the limitation. Metadata-only remains fully functional regardless of AI index availability. Discovery may offer a clearly labelled metadata-only fallback.

### Ranking

- Metadata-only: retain current requested sort behaviour. For Hybrid relevance, rank FTS5 matches by BM25 ascending then stable image ID; define deterministic ranks for structured-only matches or use them solely as hard eligibility constraints.
- AI-only and strict AND: rank by exact pooled AI similarity descending with ID tie-breaker.
- Discovery OR: fuse the two independent ranks with RRF, `1/(60 + metadata_rank) + 1/(60 + ai_rank)`; a missing contribution is zero. Rank starts at 1. Initial equal weight; keep constant/weights testable rather than exposing a tuning UI prematurely. Never add raw BM25 and cosine scores.
- Deduplicate by image ID; include metadata-only matches without embeddings. Show optional Metadata / AI / Both match badges. Do not label RRF as a probability or as AI confidence.
- Relevance descending, image ID ascending is the default Hybrid order; support current explicit sort alternatives over the materialized candidate set.

## 6. Phase E — stable result paging and facets

Create an immutable per-search generation. Use the existing background worker and result model; hydrate only the visible page and prefetch as currently appropriate. Do not rerun vector search or rank fusion on scroll.

```sql
CREATE TEMP TABLE hybrid_results (
    position INTEGER PRIMARY KEY,
    image_id INTEGER NOT NULL UNIQUE,
    relevance REAL NOT NULL,
    metadata_rank INTEGER,
    ai_rank INTEGER,
    ai_score REAL,
    match_type INTEGER NOT NULL
);
```

Temporary tables are connection-local: keep the session on its owning worker connection, or use an in-memory result-reference cache with a separate repository query for page hydration. Never rely on a TEMP table from another thread/connection. Enforce memory bounds and verify temporary disk spill cannot expose data; do not persist transient results unencrypted.

- [ ] Populate complete candidate rankings once. Preserve current 2,000-image AI display cap initially, applied after hard restrictions, pooling and threshold. For discovery OR, include full metadata results plus capped semantic candidates; intersect/union and deduplicate before assigning positions.
- [ ] For strict AND, materialize exact eligible semantic hits and apply AI display cap. Maintain exact total counts separately if display is capped. Show count/limit clearly; ANN candidates are not exhaustive counts.
- [ ] Issue keyset paging (`position > :last_position ORDER BY position LIMIT :page_size`); use current page size. Hydrate media by ID, preserving positions and existing thumbnail/preview behaviour. Do not independently page two engines and merge pages.
- [ ] Compute timeline counts over threshold-qualified results in the active folder/format and other applicable hard scope, excluding the selected date restriction and before the display cap, as the current documented AI timeline does. For Hybrid discovery compute deduplicated union counts using the same semantics; separately document capped versus total counts. Use exact scan for exact counts or explicitly label approximate counts if later product-approved. Preserve format/folder facet semantics.
- [ ] Invalidate on query/precision/scope/model/metadata/index change, re-sort cached results when appropriate, discard obsolete worker responses via generation ID, cancel when locking/closing, and bound lifetime to the unlocked database.
- [ ] Keep scroll position and selection behaviour consistent; no duplicates, wrong-order pages or stale results on rapid query changes. Save/restore Hybrid mode, text, structured filters and AI precision with Image Sets using backward-compatible schema/versioning.

**Exit gate:** Exhaustive paging tests demonstrate stable membership/order, complete union, correct counts, and no AI requery per page.

## 7. Phase F — migrate existing encrypted FAISS stores

- [ ] Use the current authenticated snapshot reader only. Inspect FAISS index type, reconstruction capabilities and existing map to recover real vectors and view identities losslessly; do not treat approximate reconstructed vectors as exact originals. If the snapshot cannot be faithfully reconstructed, regenerate embeddings from media with the existing CLIP pipeline; report unavailable originals and retain the old snapshot.
- [ ] Validate model identity, dimension, current image identity/path mapping and folder state. Skip/report stale or unknown records without deleting source files. Migrate in background with progress, bounded batches, disk-space preflight and cancellation. Keep a staging generation until complete.
- [ ] Make migration restartable and idempotent. On cancellation, crash, low disk or authentication failure, keep legacy snapshot and readable SQLite metadata, clean or resume staging safely. Do not fall back to plaintext.
- [ ] Validate counts by image/view, sampled vector values and search results; train/build index, verify encrypted close/reopen and backup/restore. Only then atomically mark Vec1 active. Keep legacy snapshot and its matching key through rollback window.
- [ ] On first successful rollout, provide clearly documented rollback and cleanup. Remove legacy files only after verification and explicit user-facing cleanup policy; do not remove original media. A previous release may not understand the new schema: document safe backup/restore and downgrade constraints.
- [ ] After migration support is stable, remove FAISS dependency, snapshot write path, duplicated encryption and mapping code in a separate reviewed change. Retain migration reader for a defined compatibility window; avoid silently dropping upgrade support from old releases.

## 8. Phase G — packaging, UI and docs

- [ ] Integrate deterministic native Vec1 build into Windows MSI, macOS Apple silicon DMG and Linux DEB/RPM targets that currently ship AI; cover relevant x86/ARM architectures and frozen application specs. Keep optional AI/platform capability checks (including existing unsupported Intel macOS behaviour). Add source/license notices and update SBOM where applicable.
- [ ] Add translated labels/tooltips, syntax help, precision controls, relevance sort, optional match badges, indexing/training progress, migration errors and cancellation. Retain accessibility and keyboard navigation.
- [ ] Update user manual, project spec, AI performance docs, backup/password protection explanation and release notes. State that original media and exports remain outside database encryption.
- [ ] Add integration tests that run against bundled SQLCipher and Vec1, not merely stock sqlite3; retain test doubles only for unit tests. Validate release artifacts on clean environments.

## 9. Verification and performance acceptance

Use reproducible fixtures generated locally plus representative real libraries with consent. Baseline the existing FAISS backend first. Record device, RAM, CPU/GPU, OS, database encryption settings, model, view count, precision and warm/cold state. Test equal image and vector counts on each backend. Proposed initial targets below are engineering targets, not measured commitments; document deviations before selecting ANN parameters.

| Area | Required test / target |
| --- | --- |
| Exact score parity | Compare normalized cosine scores to legacy/NumPy oracle; target absolute error <= 1e-5 on finite compatible vectors; investigate tie/threshold boundary differences |
| AI behaviour | Match precision thresholds, pooling, deterministic ties, empty query, disabled folders, formats, dates, sets and missing embeddings |
| Hybrid correctness | Exact metadata matches never lost in discovery; strict AND never returns out-of-scope images; union deduplicates; ordering reproducible |
| ANN recall | Proposed recall@100 >= 0.95 vs exact image-level oracle, including selective scopes; test threshold recall and tune or use exact fallback |
| Paging | Every candidate exactly once across pages; no new embedding inference or vector search on next page; stale-generation results ignored |
| Facets | Timeline counts match exact oracle before display cap and ignore active date selection as specified; format/folder counts retain current semantics |
| Encryption | Correct/wrong password, encrypted reopen, WAL/temp/staging/backup inspection using synthetic known marker data, no plaintext vector cache |
| Reliability | Insert/update/delete/disable, model changes, folder removal, rollback and migration interruption, cancellation, lock/unlock, concurrent metadata updates |
| Performance | Compare p50/p95 first-result and page latency, memory, disk, training and incremental indexing at 10k, 100k, 500k, and 1M images where hardware permits; report vectors per image separately |
| Packaging | Native smoke tests on supported release architectures; metadata-only mode works if Vec1/AI is unavailable |

Target first-page p95 no worse than legacy by more than 20% at comparable recall on representative hardware, with paging no worse than current metadata paging. Record absolute latency and resource consumption; do not declare victory on averages alone. For slow or very large exact facet calculations, run asynchronously, show pending status, and avoid misleading partial totals. Benchmark narrow and broad filters, multi-view duplicates and date histogram scans rather than only unfiltered nearest-neighbour queries.

## 10. Deliverables and recommended PR order

1. **ADR + encrypted native feasibility spike**. Dependency pin, supported matrix, actual schema/worker audit, benchmarks harness.
2. **Vec1 repository + exact AI parity**. Schema/transactions, feature switch, tests; keep FAISS default until verified.
3. **ANN optimization + migration**. Training, filtered query strategy, exact fallback, crash/reopen/rollback tests; switch only after validation.
4. **Hybrid query and paging**. Explicit AND, discovery OR, RRF, facets, generation IDs, UI and saved sets.
5. **Release hardening + gradual FAISS removal**. Packaged builds, docs, performance report, compatibility window and later cleanup.

Definition of done: new and migrated collections use a single encrypted metadata/vector database; search and paging pass correctness and performance tests; unsupported AI configurations still support normal search; installers and migration/rollback documentation are verified; no uncontrolled plaintext artifacts or lost images. Include a summary of changed files, actual commands/test results, benchmark table, and outstanding limitations in every PR. Do not claim a test passed if it was not run.

## Primary references

- Repository and current search behaviour: https://github.com/baddonkey/exif-turbo/blob/main/docs/user-manual.md#6-searching
- Existing AI performance notes: https://github.com/baddonkey/exif-turbo/blob/main/docs/ai-performance.md
- Vec1 overview/build: https://www.sqlite.org/vec1.html
- Vec1 user manual (training, filtered/streaming retrieval): https://www.sqlite.org/vec1doc.html
- Vec1 reference (native vector format, distance, training, virtual tables): https://sqlite.org/vec1ref.html
- Vec1 benchmark methodology: https://www.sqlite.org/vec1bench.html
- SQLite FTS5: https://www.sqlite.org/fts5.html
- SQLCipher architecture: https://www.zetetic.net/sqlcipher/design/

This is a proposed implementation plan based on the public documentation, not a verified source-level audit or completed migration. The initial Copilot audit and feasibility spike resolve repository-specific assumptions before implementation.
