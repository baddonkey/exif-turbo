# AI Runtime Benchmark

Phase 2 retains the exact five-view, 512-dimensional float32 FAISS index. It
changes bookkeeping and search repository lifetime, not retrieval semantics or
the embedding model. Date filtering and timeline facet changes remain separate.

## Runtime Ownership

Each application controller owns an `AiSearchSession`. Searches lease its
validated, read-only snapshot; a lock serializes loads and searches against
invalidation and close. Scans use separate mutable repositories and publish
encrypted snapshots by atomic replacement, so an active search can finish using
its previous complete generation. The next search loads the replacement.

Generation checks inspect file identity, size, modification time, and change
time for vectors, mappings, metadata, encrypted snapshots, and wrapped keys.
Unchanged generations are not decrypted, deserialized, or checksummed again.
Replacement, deletion, key changes, and explicit invalidation evict cached data;
failed validation never returns results from the previous cached generation.
These checks detect ordinary storage changes, not adversarial manipulation of
filesystem metadata. New generations still undergo integrity/authentication
validation. Password changes invalidate the cache. Closing joins workers,
releases the session, and rejects late leases. Sessions are not global and are
not reused across database controllers.

Batch duplicate checks consult the existing per-image view rows rather than
constructing a set of every vector row for every batch. This requires no second
full-index membership set. Appends, reloads, resets, and folder removal keep the
path map consistent.

## Reproduction

Run each measurement in a fresh process from the project virtual environment:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_ai_search.py --images 10000 --output logs/ai-benchmarks/10000-plain.json
.\.venv\Scripts\python.exe scripts/benchmark_ai_search.py --images 10000 --encrypted --output logs/ai-benchmarks/10000-encrypted.json
.\.venv\Scripts\python.exe scripts/benchmark_ai_search.py --images 100000 --output logs/ai-benchmarks/100000-plain.json
.\.venv\Scripts\python.exe scripts/benchmark_ai_search.py --images 100000 --encrypted --output logs/ai-benchmarks/100000-encrypted.json
```

The deterministic seed is 42, batches contain 256 images, and every image has
five normalized synthetic vectors. FAISS uses one CPU thread. Each search
returns up to 2,000 unique images with threshold 0; cached and reloaded results
must have identical paths, ranking, and scores. Each reported search median
uses three repetitions. No model, source image, SQLite hydration, GUI rendering,
filter-path lookup, or GPU is involved. "Cold" means a new repository/session,
not an operating-system disk-cache flush.

The benchmark times optimized appends and separately reconstructs/checks the
old whole-index row set before each batch. Their sum is a modeled legacy append
baseline, not a run of the previous release. Embedding generation is excluded
from append times. Peak RSS covers the entire fresh benchmark process, including
save verification, modeled bookkeeping, reloads, and cached searches; it is not
steady-state application memory or an isolated comparison of allocation peaks.

## Measurements

Measured on Windows 11 (build 26300), Intel Family 6 Model 154, 10 logical CPUs,
16 GB RAM, Python 3.13.14, FAISS 1.14.3. Times and memory are hardware/workload
observations, not release guarantees.

| Images | Storage | Disk MB | Append s | Old scan overhead s | Reload search ms | Session cold ms | Session warm ms | Peak RSS MB |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | Plaintext | 106.3 | 0.123 | 0.160 | 283 | 259 | 18 | 391 |
| 10,000 | Encrypted | 106.3 | 0.119 | 0.150 | 431 | 536 | 24 | 820 |
| 100,000 | Plaintext | 1,063.3 | 1.532 | 17.141 | 3,049 | 2,626 | 96 | 3,360 |
| 100,000 | Encrypted | 1,063.3 | 1.494 | 17.248 | 4,334 | 3,783 | 73 | 7,672 |

MB denotes decimal megabytes. Raw vectors occupy 102.4 MB at 10k images and
1,024 MB at 100k images before mappings, model memory, or temporary allocations.
The cached snapshot remains resident until generation replacement or close;
scanning concurrently may retain both a search snapshot and a mutable scan
index. Encryption still assembles/verifies complete snapshots in memory.
At 100k images, saving took 3.64 s for plaintext and 8.03 s for encrypted
storage; encrypted peak RSS reached 7.67 GB. Use an adequately provisioned
machine for the 100k encrypted benchmark. Warm timing differences between
storage modes reflect run variability, not faster search from encryption.
Compression, bounded-memory persistence, and any approximate index selection
belong to Phase 3. These synthetic results do not establish end-to-end
large-library search performance.

## Phase 3: Lower-Copy Exact Persistence

Phase 3 retains `IndexFlatIP`, all five views, float32 scores, and model
fingerprints. Encrypted saves now process 1 MiB chunks rather than assembling
the full plaintext payload, ciphertext, and decrypted verification copies.
Verification authenticates and hashes the staged file without retaining it.
Loads split decrypted chunks into their component buffers rather than assembling
and then slicing a second full plaintext snapshot. FAISS serialization is passed
as a memory view rather than copied to another full-size Python byte string.
Migration verification no longer loads the entire snapshot into memory.

The `ETAI1` snapshot format is unchanged. Old snapshots remain readable, and
the previous reader can read newly written snapshots. No rebuild or on-disk
migration is required for this change. Atomic ciphertext-only publication,
password wrapping, authentication-before-use, and fail-closed error handling
are preserved. An unauthenticated framing error is deferred until the GCM tag
has been verified, so header tampering cannot become a rebuildable format error.

This is lower-copy persistence, not constant-memory indexing. FAISS's live
index and its serialized representation still occupy memory; loaded index bytes,
mapping dictionaries, model memory, and concurrently active snapshots also remain.
Save/load speed may trade off against reduced peak allocation. Exact score and
ranking compatibility is the acceptance gate, rather than adopting lossy
compression to meet a memory target without real-image quality evidence.

Fresh-process encrypted measurements using the same Phase 2 harness and machine:

| Images | Phase | Peak RSS MB | Save s | Reload/search median ms | Warm search median ms |
| ---: | --- | ---: | ---: | ---: | ---: |
| 10,000 | Phase 2 | 820 | 0.654 | 431 | 24 |
| 10,000 | Phase 3 | 393 | 0.895 | 667 | 18 |
| 100,000 | Phase 2 | 7,672 | 8.028 | 4,334 | 73 |
| 100,000 | Phase 3 | 3,364 | 5.599 | 5,439 | 76 |

Peak process RSS fell about 56% at 100k images. The 100k save was faster, but
reload/search was slower in this run; chunk processing and allocation strategy
trade latency for reduced memory pressure. Warm exact-search results matched
reloaded results. Disk sizes were unchanged (106.3 MB and 1,063.3 MB).
These are single-machine observations with three search repetitions, not
statistical release guarantees or isolated save/load memory peaks. In-memory
model weights, source decoding, and concurrent scan/search residency remain
outside the synthetic workload.

### Compression Evaluation

Use `--compare-indexes --repeats 5` with the benchmark commands above to compare
FAISS float16 and 8-bit scalar quantization against the exact reference. The
candidate path max-pools all five views per image and reports image recall at
100, maximum score error, threshold eligibility changes at 0.18/0.20/0.22,
and serialized vector size. Queries and embeddings are independent synthetic
normalized vectors; this does not certify semantic relevance or threshold
stability for real image collections. Full-population candidate query timings
are not comparable to the production top-2,000 search timings.

At 10k images and five queries, float16 halved serialized vector bytes and
retained 100% mean image recall at 100, but changed image scores by up to
0.000039. Scalar8 reduced vector bytes to one quarter, achieved 98.8% recall,
and changed scores by up to 0.001953. Neither changed threshold eligibility in
that small synthetic sample. Both are lossy; neither is enabled in production.
At 100k images, float16 used 512.0 MB of serialized vectors with 100% mean
recall and maximum score error 0.000048. Scalar8 used 256.0 MB with 98.6%
recall and maximum score error 0.008576; one image/query eligibility pair changed
at each of the three thresholds. The exact reference used 1,024.0 MB.
Product quantization and approximate nearest-neighbor adoption are deferred
until a representative relevance corpus and quality tolerances are approved.

The same benchmark measures mapping alternatives. At 10k images the current
mapping was 3.879 MB, zlib-compressed JSON was 0.268 MB, and a compact ordered
five-view mapping was 0.340 MB. The ordered representation assumes every image
has every view and cannot represent arbitrary partial/legacy rows as-is.
Mapping-only savings are small beside 102.4 MB of raw vectors and do not reduce
the live FAISS index. No mapping format change is included in this phase.
At 100k images the mapping sizes were 39.289 MB for current JSON, 2.664 MB
for zlib-compressed JSON, and 3.400 MB for the restricted compact representation.