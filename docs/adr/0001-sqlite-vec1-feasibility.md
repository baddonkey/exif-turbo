# ADR 0001: SQLite Vec1 feasibility for encrypted vector storage

- Status: **Windows x64 validated; Linux/macOS release-matrix validation pending**
- Date: 2026-11-26
- Scope: Phase A feasibility and initial Phase B repository for the proposed
  FAISS-to-Vec1 migration and initial Phase C exact-search evaluation

## Context

The migration plan proposes storing image vectors in the existing SQLCipher
database, while preserving CLIP, metadata search, and the current AI behavior.
The first gate is to load Vec1 through the application's SQLCipher connection
and verify encrypted create, insert, query, delete, close, and reopen before
changing production storage.

## Audited baseline

- [`_connection.py`](../../src/exif_turbo/data/_connection.py) opens the
  application database with SQLCipher, enables WAL, sets `temp_store=MEMORY`,
  and enables foreign keys.
- [`image_index_repository.py`](../../src/exif_turbo/data/image_index_repository.py)
  owns the `images` table, FTS5 indexes, foreign-key relationships, and the
  `completed_migrations` migration ledger.
- AI vectors are currently held in a separate FAISS `IndexFlatIP` snapshot,
  not in the metadata database. [`ai_vector_repository.py`](../../src/exif_turbo/data/ai_vector_repository.py)
  uses normalized float32 inner-product vectors, the configured model
  dimension, and path/view mappings. The default profile is 512-dimensional.
- [`ai_indexer_service.py`](../../src/exif_turbo/indexing/ai_indexer_service.py)
  builds a full-image view plus four corner crops where the image supports
  cropping, and normalizes image and text vectors. Search pools views by the
  maximum similarity per image.
- [`ai_search_worker.py`](../../src/exif_turbo/ui/workers/ai_search_worker.py)
  applies eligible-path restrictions before the display cap, returns exact
  threshold-qualified facet paths, and caps displayed AI results at 2,000.
  The existing AI mode remains available alongside Hybrid.
- For password-protected databases,
  [`ai_vector_storage.py`](../../src/exif_turbo/data/ai_vector_storage.py)
  stores the FAISS index, path/view mapping, and model metadata in an
  authenticated encrypted snapshot separate from the SQLCipher database.
- The default AI thresholds remain 0.18, 0.20, and 0.22, as documented in the
  [search manual](../user-manual.md#6-searching). Windows x64 exact-search
  parity passed; portability remains unverified.
- The dependency lock resolves `sqlcipher3` 0.6.2. The active Python 3.13.14
  runtime reports SQLCipher 4.12.0 and SQLite 3.51.1. The project environment
  markers include Windows AMD64, Linux x86_64/aarch64, and macOS arm64. CI tests
  Windows and Ubuntu on Python 3.11/3.13 and macOS arm64 on Python 3.13.

## Vec1 source candidate

The official SQLite documentation identifies Vec1 version 0.8 as its current
release and documents the extension's vector format, cosine distance function,
virtual-table CRUD, and rebuild/query APIs. Vec1 remains pre-1.0, so its
compatibility and persistence behavior need to be verified against a pinned
source revision:

- [Vec1 overview and build instructions](https://www.sqlite.org/vec1.html)
- [Vec1 reference](https://sqlite.org/vec1ref.html)

The candidate source is the upstream
[Vec1 source at commit `803d64f73ba09b9a0ea338b5c621493ac857d1e3`](https://github.com/sqlite/sqlite/blob/803d64f73ba09b9a0ea338b5c621493ac857d1e3/ext/vec1/vec1.c),
file `ext/vec1/vec1.c`, declaring `VEC1_VERSION "0.8"`. Its SHA-256 is
`2fdaf637bf06639780f4c26ee165dbdbaa50849362f87d86e8388537567a2701`.
The source header contains an author copyright disclaimer. Recheck the
immutable commit and checksum when introducing a reproducible build.

The official Windows build guidance uses `nmake /F Makefile.msc vec1.dll`.
That target was subsequently used for the Windows x64 validation below.

## Feasibility probe

On the current Windows x64 / Python 3.13 host:

- An encrypted database created with the application's
  `open_encrypted_connection` was written, closed, and reopened successfully.
  Its file header was not the plaintext SQLite header, and reopening with a
  wrong password raised `sqlcipher3.DatabaseError`.
- The connection reported `temp_store=MEMORY` and `journal_mode=wal`.
- `enable_load_extension(True)` and `enable_load_extension(False)` are
  available on the active SQLCipher connection.

The first probe found that Vec1 was not registered and no compiler was
available. After the user approved installing local Windows build tools, the
pinned source was built and loaded through the existing SQLCipher driver. The
full Windows result is recorded below. This does not establish compatibility
across the release matrix, trained ANN behavior, or crash-safe migration.

## Windows x64 native validation

The pinned Vec1 source was built with SQLite's Windows `Makefile.msc` target
(`nmake /F Makefile.msc vec1.dll`) using the SQLite 3.51.1 headers that match
the active SQLCipher runtime. The build used MSVC 19.44 / NMake 14.44. The
resulting temporary DLL exports `sqlite3_extension_init`, has no dependency
beyond `KERNEL32.dll`, and does not link a second SQLite library. The official
target produced scalar and AVX2 implementations with runtime CPU dispatch.
`SELECT vec1_info()` reported `version 0.8 (AVX2, multi-threaded)`.

The encrypted SQLCipher smoke test passed:

- Loaded Vec1 on the application connection, then disabled extension loading.
- Created a Vec1 virtual table using exact cosine mode; inserted, updated,
  queried, and deleted vectors.
- Closed and reopened the encrypted database, reloaded the extension, reran
  the exact cosine query, and verified vector/mapping persistence and
  `PRAGMA integrity_check`.
- Rejected a wrong database password. A synthetic path marker and a raw vector
  marker were absent from the database, WAL, and SHM files while open.
- Compared exact image-level max pooling and ranking for 12 synthetic images,
  24 normalized 512-dimensional vectors, and two views per image against
  FAISS `IndexFlatIP`. Ranking and threshold membership at 0.18, 0.20, and
  0.22 matched; maximum absolute score error was `4.12e-8`.

MSVC emitted non-fatal warnings (`C4456`, `C4244`, `C4310`, and `C4701`). The
`C4701` warning is on a location structure initialized by
`vec1FindByRowid`; the remaining warnings should be reviewed against upstream
before selecting release warning policy. No changes were made to Vec1 source,
and the temporary DLL was not added to the application.

## Phase B repository probe

The initial repository implementation and its focused integration tests use
the same SQLCipher database for image vectors, mappings, and model metadata.
Image deletion is recorded through an ordinary SQLite trigger on the mapping
table; the trigger writes vector row IDs to an encrypted pending-delete table
and does not reference the Vec1 virtual table. This was verified by reopening
the database through `ImageIndexRepository` without loading Vec1, deleting an
image, observing the queued row ID, and then reopening through Vec1 to drain
the queue. This preserves metadata-only database access while deferring
physical vector cleanup until an AI-capable connection is available.

Focused Windows tests cover Vec1 CRUD and scoped exact search, model-profile
compatibility, invalid vector rejection, transactional upsert rollback,
metadata-only deletion, exact-index rebuild, and the existing FAISS repository
contract. Both a closed-database copy and a SQLCipher online backup reopened
with their vectors intact and rejected a wrong password on Windows. The
production default remains FAISS; the Vec1 repository is not yet selected by
the application, and native packaging has not been added. The targeted
Vec1/FAISS/session/indexing/worker test run passed: 96 tests.

## Phase C exact-search and ANN evaluation

The encrypted repository's scoped exact search was compared with FAISS and an
independent NumPy cosine oracle using synthetic 512-dimensional vectors,
two views per image, thresholds 0.18/0.20/0.22, and a restricted scope.
Threshold-boundary fixtures on either side of each threshold, pooled ranking,
and capped results matched within 1e-5. Exact ties now follow FAISS's path
ordering. Failed first-time schema creation rolls back, and the reported vector
count excludes vectors pending deletion.

On the tested SQLite version, the original scoped query plan scanned the full
embedding map. The query now starts with the temporary scope and uses indexed
image path and image/view lookups before fetching Vec1 rows. This is a query
plan observation, not a large-library performance measurement.

An exploratory synthetic ANN run used
[`benchmark_vec1_ann.py`](../../scripts/benchmark_vec1_ann.py) with the pinned
Windows DLL, an in-memory SQLCipher connection, 1,600 random 512-dimensional
vectors, eight random queries, 16 buckets, no compression, 200 candidates and
exact reranking to 100. On Windows 11 / Python 3.13.14 / FAISS 1.14.3:

| nprobe | Mean recall@100 | Minimum recall@100 | Query p50 | Query p95 |
| ---: | ---: | ---: | ---: | ---: |
| 0.25 (four buckets) | 0.34 | 0.26 | 4.70 ms | 6.21 ms |
| 16 (all buckets) | 1.00 | 1.00 | 4.42 ms | 8.68 ms |

Training took 0.020 s and rebuilding 0.037 s. The seed fixes input vectors,
but Vec1 training may produce different results across runs. Reproduce with
`python scripts/benchmark_vec1_ann.py --extension <path-to-vec1-library>`.
This tiny single-view synthetic experiment is not a representative benchmark,
does not measure encrypted disk or application latency, and does not establish
real-library recall. The four-bucket configuration did not meet the proposed
0.95 recall target. ANN remains experimental; exact search remains the Vec1
default, and FAISS remains the application default.

The experimental repository can also train a cosine index and rebuild it
transactionally on a background worker. It selects a bucket count from the
collection size, requires at least 128 vectors, and keeps exact search as the
default. Its separate experimental global ANN method overfetches vector
candidates, reranks with exact cosine distance, and pools by image; scoped and
threshold-complete queries still use exact search. Training cancellation rolls
back the rebuild. This does not establish representative ANN recall or
performance, and the worker is not exposed as a production control.

## Initial FAISS import safeguard

The experimental repository import accepts only an authenticated encrypted
FAISS snapshot with the matching model and view strategy. It requires an
`IndexFlatIP` with valid, unique image/view mappings and finite normalized
vectors; unsupported indexes require re-encoding rather than approximate
reconstruction. The migration-specific loader must validate the model and view
strategy; a normal search load cannot authorize migration. Imported float32
bytes are checked against the stored Vec1
rows. Snapshot paths absent from the metadata database are skipped and
counted. Disabled folders are retained so re-enabling them does not require
re-encoding.

Import into an empty Vec1 index runs in a single SQLCipher transaction.
Cancellation, invalid source rows, and other errors roll back the transaction;
other database connections do not see partial rows. A Windows test forcibly
exits the importing process mid-transaction, reopens the encrypted database,
and successfully retries. This tests process interruption, not power loss.
The authenticated FAISS snapshot is retained, and a nonempty Vec1 destination
is never overwritten. A repeat import succeeds only after checking every
current image/view and vector byte against the authenticated snapshot and
rejecting extra or missing destination rows. A post-reopen test also compares
an imported search against FAISS.

Before new writes, a disk-space preflight reserves 16 MiB plus twice the
estimated vector and mapping overhead (2,048 bytes per vector plus its
float32 data). This heuristic cannot guarantee enough space or prevent
concurrent disk use; SQLCipher write failures still roll back.
The experimental migration worker can alternatively stage the authenticated
snapshot in separate Vec1 tables inside the encrypted database. It commits
bounded batches, verifies each vector and samples search parity, detects
concurrent metadata or snapshot changes, and leaves the existing Vec1 and
FAISS indexes untouched. A new stage is built separately and replaces the last
completed stage in one transaction only after verification. Cancellation
removes the new build; a process interrupted between batches can restart by
replacing its incomplete build without deleting the last completed stage.
The worker verifies a temporary encrypted online backup of the new build
against the source before replacing that stage. It then closes and reopens the
encrypted database and verifies the staged rows again before reporting
completion. A failed backup leaves the previous completed stage intact. The
temporary backup is deleted on normal
completion, cancellation, or error; an abrupt process exit can leave an
encrypted temporary copy behind. The worker reports image contents as
unverified because legacy snapshots do not contain the media stamps needed to
establish freshness. Staging stores a fingerprint of the authenticated snapshot
and each image's current indexed modification time and size. Reverification
rejects a different snapshot or changed indexed stamps, including after a
reopen; these stamps cannot prove that the original legacy embeddings were
fresh. A separate Windows test rejects an incorrect backup password.

The migration-specific reader authenticates the snapshot before giving FAISS
access to its index bytes, using a temporary SQLCipher database with the same
password and bounded encrypted chunks instead of holding a second serialized
index in memory. It checks disk space and supports cancellation; temporary
files are removed on normal completion or error, but an abrupt process exit
may leave an encrypted scratch file. FAISS still holds the full index in
memory, and the mapping is also loaded in memory, so total migration memory is
not bounded independently of collection size.

This is not yet a complete migration: the worker is not connected to the UI,
and promotion and backend activation are not implemented. Unsupported index re-encoding,
media-content freshness, durable metadata-generation identity at promotion,
and enforcement of backup/restore verification at promotion also remain
unimplemented. These limitations must be addressed before exposing migration
or activating Vec1.

## Hybrid search integration

Hybrid search parses a single positive `ai:="..."`
clause and builds immutable in-memory result references. Discovery merges
metadata and exact semantic matches with reciprocal-rank fusion; explicit AI
clauses require the metadata and semantic branches to match. It retains all
metadata matches, caps displayed semantic candidates at 2,000, and keeps
uncapped, pre-date paths for timeline facets. The experimental worker hydrates
only the first page and reports an empty AI index rather than silently falling
back. Searches exceeding one million scoped images fail explicitly to bound
the in-memory reference set.

The controller and QML expose Hybrid search using the existing FAISS backend.
Pages hydrate image IDs from the immutable ranking without a new vector query.
Changing the sort order reorders a still-current ranking without encoding or
searching again; a changed database or FAISS generation triggers a new search.
The controller rejects stale generations when the metadata database or FAISS
snapshot changes. Image Sets store a separate versioned Hybrid view; restoring
the view does not reapply or alter the set's existing membership filter.
Cancellation is checked around the native vector call, which itself is not
interruptible. Production Vec1 activation, representative large-library
performance measurements, and cross-platform release validation remain open.

## Decision

Proceed with the Windows-validated Vec1 repository and exact-search work while
deferring Linux/macOS builds and validation, as directed by the user. Keep
FAISS as the production default until the supported release matrix, migration,
packaging, and parity gates pass. Do not bypass SQLCipher, introduce an
unencrypted sidecar, or treat successful extension loading as proof of release
readiness.

## Required work to clear the gate

1. Reproduce the pinned build on Linux x86_64/aarch64 and macOS arm64 using the
   target SQLCipher/SQLite extension ABI. Confirm CPU dispatch, binary loading,
   and macOS signing on each packaged architecture.
2. Register only that bundled binary on an application SQLCipher connection,
   disable further extension loading immediately, and verify `vec1_info()`.
3. In a disposable password-protected database, test Vec1 table creation,
   finite float32 insert, exact cosine query and score, update/delete, close,
   encrypted reopen, and wrong-password rejection. Inspect WAL, temporary
   storage, and the database directory for plaintext artifacts.
4. Compare Vec1 exact scores and pooled image rankings with the existing FAISS
   behavior and an independent numeric oracle, including threshold boundaries
   and multiple views.
5. Add reproducible builds and smoke tests for the supported release targets.

The user has explicitly deferred Linux and macOS work, so it remains a
production-release gate rather than a blocker for the current Windows
implementation. Do not switch the production backend or remove FAISS until it
is cleared.

No representative Vec1 application, encrypted-disk, or resource benchmark has
been run. The existing FAISS measurements in
[`ai-performance.md`](../ai-performance.md) are not comparable to the
synthetic ANN experiment.
