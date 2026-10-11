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