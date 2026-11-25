---
name: bottleneck-audit
description: Find performance bottlenecks across code, SQL/APIs, frontends, builds, and runtimes, explain why each degrades speed or resources, and propose ranked fixes with benchmarks and tradeoffs. Use when diagnosing slow endpoints, high latency, CPU/RAM spikes, N+1 queries, UI lag, or slow builds/CI. Exclude pure refactoring, motion polish (improve-animations), or skill token audits (skill-forge).
compatibility: Python 3 stdlib
---

# Bottleneck Audit

Measure or run bounded static triage before reading large files. Prove *why* a path dominates latency, throughput, CPU, memory, or build time (Amdahl's Law) before proposing optimizations. Always reply in the user's language.

## 1. Five-stage workflow

1. **Scope & Baseline:** Pin down the critical path and target metric (`p50`/`p95`/`p99` latency, RPS, CPU, peak RSS/OOM, UI frame time, or build/CI duration).
   - If the target is runnable, measure a baseline first via `scripts/bench-cmd.py` (or a stack command from `references/profiling-commands.md`).
   - Classify the profile using `(user + sys) / wall`: `>= 0.75` is **CPU-bound**, `<= 0.30` is **I/O, DB, network, or lock wait**, and `sys / (user + sys) >= 0.40` flags **syscall/filesystem overhead**.
   - If the environment is static-only (no execution/DB access), label every claim as a static hypothesis and never invent unmeasured percentages.
2. **Bounded Triage:** Run `scripts/scan-hotspots.py <target> [--domain ...] [--limit 25]` first to detect stacks, available profilers, oversized files/assets, and context-aware `file:line` suspects in one compact output. Load at most one relevant `references/*.md` file on demand.
3. **Verify Root Cause:** Read only the implicated hot path (entry point, callers, loop/query boundaries, and downstream sinks). Separate symptom from mechanism: algorithmic complexity `O(...)`, `1+N` round-trips, sequential `await`, event-loop blocking, lock contention, allocation/GC churn, or forced layout reflow. Focus on the top 1–3 dominant constraints; defer cold-path micro-optimizations.
4. **Design Optimizations:** For each confirmed bottleneck, give a concrete fix, explain *why* it relieves the constraint, state **tradeoffs & risks** (RAM footprint, stale cache invalidation, write amplification, backpressure), and specify how to verify it. Prefer algorithmic, query/index, batching, concurrency, and streaming fixes over speculative caching or micro-tuning.
5. **Verify (when applying changes):** Apply one high-leverage change at a time and re-run `scripts/bench-cmd.py --compare baseline.json` (or `EXPLAIN ANALYZE` / profiler diff) to prove the real delta before moving on.

## 2. Required report format

Use this structure (localized to the user's language):

```markdown
## Verdict & Baseline
- **Primary constraint:** <CPU | DB/SQL | Network I/O | Memory/GC | Render/Bundle | Build/CI>
- **Scope & baseline:** <measured p50/p95, CPU ratio, RSS — or explicit static-only note>

## Bottlenecks (P0 -> P2)
### [P0] <Title> — <file:line>
- **Evidence:** <exact code construct, query shape, or profiler counter>
- **Why it's a bottleneck:** <mechanism, scaling curve, and impact on the critical path>
- **Optimization:** <specific code/query/config change>
- **Tradeoffs & Verification:** <risks/cost + command or metric to confirm>

## ROI Action Plan
| Priority | Change | Expected Impact | Effort / Risk |
| --- | --- | --- | --- |

## Deferred / Not a Bottleneck
- <inspected cold or non-dominant paths and why they are low priority>
```

## 3. Bundled scripts (relative to this skill directory)

| Script | Purpose |
| --- | --- |
| `scripts/scan-hotspots.py [TARGET] [--domain LIST] [--limit 25] [--json]` | Stack probe, available profilers, large assets, and loop/async/DB/frontend suspects |
| `scripts/bench-cmd.py [--warmup 1] [--runs 5] [--save F] [--compare F] -- CMD...` | Measure wall `p50`/`p95`, `(user+sys)/wall` CPU ratio, peak RSS, and before/after delta |

Minimal workflow example:

```bash
python3 scripts/scan-hotspots.py . --domain db,io --limit 20
python3 scripts/bench-cmd.py --warmup 1 --runs 5 --save /tmp/base.json -- python3 app.py
```

## 4. Progressive disclosure references

- Read `references/backend-db-io.md` when auditing SQL/ORM queries, API/network waterfalls, async event-loop blocking, concurrency locks, or memory/GC churn.
- Read `references/frontend-build.md` when auditing bundle size, React/DOM rendering, layout thrash, Vite/Webpack/Docker builds, or slow CI pipelines.
- Read `references/profiling-commands.md` when you need low-overhead `EXPLAIN`, `cProfile`/`py-spy`, Node `--cpu-prof`, Go `pprof`, Rust timings, or Linux syscall commands.
