# Low-Overhead Profiling & Verification Commands

Use these bounded commands to confirm hypotheses before and after editing. Prefer top-N summaries over full raw dumps.

## 1. SQL & Databases

- **PostgreSQL — execution plan + real I/O buffers (run on read-only replica or wrapped in `BEGIN; ... ROLLBACK;` for mutations):**
  ```sql
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) <query>;
  ```
  Look for `Seq Scan` on large tables, `Rows Removed by Filter` >> returned rows, `Sort Method: external merge Disk`, and `Buffers: shared read` spikes.
- **PostgreSQL — top 15 cumulative slow queries:**
  ```sql
  SELECT calls, round(total_exec_time::numeric, 1) AS total_ms,
         round(mean_exec_time::numeric, 2) AS mean_ms, rows, left(query, 120) AS sql
  FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 15;
  ```
- **SQLite — query plan & index usage:**
  ```bash
  sqlite3 app.db "EXPLAIN QUERY PLAN <query>;"
  ```

## 2. Python

- **Top 20 cumulative / self-time hotspots (stdlib `cProfile`):**
  ```bash
  python3 -c "import cProfile, pstats, runpy; p=cProfile.Profile(); p.enable(); runpy.run_path('app.py', run_name='__main__'); p.disable(); pstats.Stats(p).sort_stats('cumtime').print_stats(20)"
  ```
- **Live sampling profiler without code edits (low overhead, attaches to PID or runs child):**
  ```bash
  py-spy top --pid <PID>
  py-spy record -o /tmp/profile.svg -- python3 app.py
  ```
- **Peak memory & top 15 allocation call sites (`tracemalloc`):**
  ```bash
  python3 -X tracemalloc=5 -c "import tracemalloc, runpy; runpy.run_path('app.py', run_name='__main__'); print('\n'.join(str(s) for s in tracemalloc.take_snapshot().statistics('lineno')[:15]))"
  ```

## 3. Node.js / TypeScript / Frontend Bundles

- **V8 CPU & Heap profiles (bounded post-run inspection):**
  ```bash
  node --cpu-prof --cpu-prof-dir=/tmp/prof app.js
  node --heap-prof --heap-prof-dir=/tmp/prof app.js
  ```
- **Event-loop delay & GC tracing (check for sync blocking or GC thrash):**
  ```bash
  node --trace-gc app.js 2>&1 | head -n 40
  ```
- **TypeScript compiler bottleneck breakdown:**
  ```bash
  npx tsc --noEmit --extendedDiagnostics
  ```
- **Vite / Rollup / esbuild bundle composition (inspect largest chunks/modules without GUI):**
  ```bash
  npx vite build --mode production
  # or with esbuild directly:
  npx esbuild src/index.ts --bundle --metafile=/tmp/meta.json --outfile=/tmp/out.js && \
    node -e "const m=require('/tmp/meta.json'); console.table(Object.entries(m.inputs).sort((a,b)=>b[1].bytes-a[1].bytes).slice(0,20).map(([k,v])=>({file:k,kb:(v.bytes/1024).toFixed(1)})))"
  ```

## 4. Go & Rust

- **Go benchmarks + CPU/allocation profiles (top 20):**
  ```bash
  go test -bench=. -benchmem -cpuprofile=/tmp/cpu.prof -memprofile=/tmp/mem.prof ./...
  go tool pprof -top -nodecount=20 /tmp/cpu.prof
  go tool pprof -top -alloc_space -nodecount=20 /tmp/mem.prof
  ```
- **Rust compile-time bottleneck report & runtime perf:**
  ```bash
  cargo build --release --timings
  perf record -F 99 -g -- ./target/release/<bin> && perf report --stdio --no-children | head -n 60
  ```

## 5. HTTP & Linux System

- **Single-request timing breakdown (DNS, TCP, TLS, TTFB, total):**
  ```bash
  curl -sS -o /dev/null -w "dns=%{time_namelookup}s connect=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s size=%{size_download}B\n" http://localhost:8080/api/endpoint
  ```
- **Quick HTTP load check (only against local/dev targets):**
  ```bash
  oha -n 500 -c 20 --no-tui http://localhost:8080/api/endpoint
  # or: wrk -t2 -c20 -d10s http://localhost:8080/api/endpoint
  ```
- **Syscall & filesystem bottleneck check (`strace` summary):**
  ```bash
  strace -f -c -- <command> 2>&1 | tail -n 30
  ```
- **CPU vs I/O wait snapshot (1s interval, 5 samples):**
  ```bash
  pidstat -u -d -r 1 5 -p <PID>
  ```
