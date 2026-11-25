# Backend, Database, I/O & Memory Bottlenecks

Load this reference when triaging SQL/ORM, network/API, async runtime, lock contention, or memory/GC suspects.

## 1. Database & ORM

### N+1 queries inside loops
- **Why:** Each loop iteration incurs a full DB network round-trip + query parse/plan (`1 + N` latency and connection hold time).
- **Verify:** Enable SQL query logging per request or check `scan-hotspots.py` `db-n-plus-one` hits; count query count vs item count.
- **Optimization:** Batch with `WHERE id IN (...)` / `ANY($1)`, `JOIN`, ORM eager loading (`select_related` / `prefetch_related` / `include`), or DataLoader batching.
- **Tradeoff:** Larger single result set in memory; avoid over-fetching unused columns or deep nested joins causing row multiplication.

### Missing or misordered composite indexes
- **Why:** Queries fall back to `Seq Scan` (`O(N)`) or filter thousands of rows after scanning a low-selectivity leading index column.
- **Verify:** Run `EXPLAIN (ANALYZE, BUFFERS)` and check `Seq Scan` or high `Rows Removed by Filter`.
- **Optimization:** Add index ordered `equality columns -> range/sort columns` (ESR rule), or a covering index (`INCLUDE (...)`) for index-only scans.
- **Tradeoff:** Slower `INSERT`/`UPDATE`/`DELETE` (write amplification) and extra disk/RAM cache consumption.

### Non-sargable predicates & leading wildcards
- **Why:** Wrapping indexed columns in functions (`LOWER(col)`, `DATE(ts)`) or `LIKE '%term%'` disables B-tree range lookups.
- **Verify:** Query plan shows `Seq Scan` despite an index on `col`.
- **Optimization:** Rewrite as range predicates (`ts >= $1 AND ts < $2`), use expression/functional indexes, or use GIN trigram (`pg_trgm`) / full-text indexes for substring search.
- **Tradeoff:** Expression and GIN indexes are larger and noticeably heavier on write throughput.

### Deep `OFFSET` pagination & unbounded queries
- **Why:** `OFFSET 100000 LIMIT 50` forces the DB to scan and discard 100,000 rows (`O(offset + limit)`); unbounded `.findAll()`/`.objects.all()` spikes DB I/O and app RSS.
- **Verify:** Latency grows linearly with page number; memory spikes on large tables.
- **Optimization:** Switch to keyset (cursor) pagination (`WHERE (created_at, id) < ($1, $2) ORDER BY created_at DESC, id DESC LIMIT 50`) and enforce hard max page limits.
- **Tradeoff:** Cannot jump directly to arbitrary page numbers ("Page 47") without auxiliary count/anchor logic.

### `SELECT *`, long transactions, & pool exhaustion
- **Why:** `SELECT *` breaks covering index-only scans, forces TOAST decompression, and inflates serialization; holding transactions open across HTTP calls stalls writers and exhausts the connection pool (`pool_wait_ms`).
- **Verify:** High pool acquisition wait, lock waits in `pg_stat_activity`, or large network payload per row.
- **Optimization:** Project only needed columns; move external HTTP/file work outside DB transactions; bound pool size and add PgBouncer/transaction pooling.
- **Tradeoff:** Strict column projections require updating queries when new fields are needed; shorter transactions may require explicit idempotency/compensation.

## 2. Network & Async I/O

### Sequential `await` / serial RPC waterfall
- **Why:** Independent calls awaited one-by-one inside a loop or handler sum latencies (`N * RTT`) instead of overlapping them (`max(RTT)`).
- **Verify:** Trace spans show stair-stepped sequential bars with no data dependency between requests.
- **Optimization:** Group independent requests with bounded concurrency (`asyncio.Semaphore` + `gather`, `p-limit` + `Promise.all`, worker pool, or `errgroup`).
- **Tradeoff:** Higher peak downstream concurrency; always cap in-flight concurrency and apply timeouts so downstream services are not overwhelmed.

### Sync/blocking calls on an async event loop
- **Why:** `fs.readFileSync`, `pbkdf2Sync`, `time.sleep`, `requests.*`, or CPU loops on the Node/asyncio event loop stall *every* concurrent request on that worker.
- **Verify:** Tail latency (`p99`) spikes across unrelated endpoints under modest load; event-loop lag monitor spikes.
- **Optimization:** Use async I/O (`fs.promises`, `httpx.AsyncClient`, `asyncio.sleep`) and offload heavy CPU work to worker threads/process pools (`worker_threads`, `ProcessPoolExecutor`).
- **Tradeoff:** Worker pools add IPC/serialization overhead—only offload tasks exceeding a few milliseconds.

### Missing connection reuse (keep-alive) & non-streaming payloads
- **Why:** Creating a new HTTP client/TCP+TLS socket per request wastes 1–3 RTTs + TLS handshake CPU; reading huge payloads into memory (`await res.text()` / `read_bytes()`) spikes RSS and GC pauses.
- **Verify:** High `time_connect` / `time_appconnect` in `curl -w` or elevated RSS during file/export endpoints.
- **Optimization:** Reuse shared HTTP clients/sessions (`httpx.AsyncClient`, `http.Agent({keepAlive: true})`, `http.Client`); stream large uploads/downloads/NDJSON responses.
- **Tradeoff:** Shared clients need explicit idle timeouts and connection limits to avoid stale sockets or FD exhaustion.

## 3. Concurrency & Memory / GC

### Lock contention & false serialization
- **Why:** Holding a mutex/global lock across I/O or hot shared counters forces parallel workers into a single-file queue (`(user + sys)/wall` stays low while latency rises with concurrency).
- **Verify:** Throughput plateaus or drops as threads/workers increase; high `futex`/mutex wait in profiler.
- **Optimization:** Narrow critical sections (do I/O outside locks), shard locks by key, use lock-free atomics/channels, or snapshot immutable state before work.
- **Tradeoff:** Finer-grained locking increases state-invariant complexity and requires strict lock ordering to prevent deadlocks.

### Allocation churn & quadratic accumulator copies
- **Why:** Patterns like `{...acc, [k]: v}` inside `.reduce()`, repeated `re.compile()`/`new RegExp()`, `JSON.parse(JSON.stringify(x))`, or `list.pop(0)` / `arr.shift()` in loops turn `O(N)` into `O(N^2)` and flood GC.
- **Verify:** Heap profiler shows high allocation rate in short-lived objects; `(user + sys)/wall >= 0.75` with heavy GC pause time.
- **Optimization:** Mutate a local `Map`/`dict`/array inside the reducer, hoist regex compilation to module scope, use `structuredClone` or shallow updates, and use `collections.deque` or `Set`/`dict` for `O(1)` lookup/pop.
- **Tradeoff:** Local mutation inside a fresh object must not leak or mutate caller inputs.

### Unbounded in-memory caches & retry storms
- **Why:** Plain `dict`/`Map` caches without eviction leak RSS until OOM; retries without exponential backoff + jitter multiply traffic during partial outages.
- **Verify:** Monotonically rising RSS over uptime; traffic spikes coincide with error bursts.
- **Optimization:** Bound caches by entry count or bytes (`functools.lru_cache(maxsize=...)`, LRU with TTL) and enforce jittered exponential backoff + circuit breakers.
- **Tradeoff:** Eviction introduces cold misses; TTLs trade freshness for lower DB/upstream load.
