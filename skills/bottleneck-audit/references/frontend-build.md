# Frontend, Rendering, Build & CI Bottlenecks

Load this reference when triaging slow UI loads, frame drops, bloated JS bundles, or sluggish local builds and CI pipelines.

## 1. Frontend Network & Bundles

### Request & component fetch waterfalls
- **Why:** Fetching data sequentially inside nested components (`Parent` renders -> fetches -> mounts `Child` -> fetches) serializes network RTTs and delays LCP/TTI.
- **Verify:** Browser Network waterfall shows chained request bars triggered sequentially after JS execution.
- **Optimization:** Hoist/parallelize fetches at route loader or server boundary (`Promise.all`), prefetch critical routes/data, and stream SSR/RSC payloads.
- **Tradeoff:** Route-level prefetching can slightly over-fetch data for branches the user never visits.

### Bundle bloat, barrel imports & full-library imports
- **Why:** `import _ from 'lodash'`, `import * as Icons from 'lucide-react'`, or deep barrel `index.ts` re-exports pull megabytes of unused code, hurting parse/eval CPU and download time.
- **Verify:** Inspect Vite/Rollup/esbuild `metafile` or `source-map-explorer`; check `scan-hotspots.py` `frontend-full-lib-import`.
- **Optimization:** Use direct subpath imports (`lodash-es/debounce`, `lucide-react/dist/esm/icons/...`), dynamic `import()` for heavy routes/charts/editors, and native `Intl`/CSS instead of legacy date/utility libs.
- **Tradeoff:** Code splitting adds extra async chunks; verify critical path chunks don't create micro-waterfalls.

### Unoptimized LCP media & web fonts
- **Why:** Uncompressed hero PNGs, missing `width`/`height` (CLS), `loading="lazy"` on the LCP image, or unsubsetted render-blocking fonts stall First Contentful Paint and LCP.
- **Verify:** Check largest asset sizes (`scan-hotspots.py` large assets section) and Lighthouse/Web Vitals LCP breakdown.
- **Optimization:** Convert large photos to AVIF/WebP with responsive `srcset`, set `fetchpriority="high"` (never `lazy`) on LCP hero media, inline critical CSS, and subset fonts with `font-display: swap`.
- **Tradeoff:** `font-display: swap` can cause a brief font-swap flash unless fallback metrics match (`size-adjust`).

## 2. DOM, Rendering & Main Thread

### Layout thrashing (forced synchronous reflow)
- **Why:** Reading geometry (`getBoundingClientRect()`, `offsetHeight`, `offsetWidth`, `scrollTop`, `clientWidth`) immediately after mutating DOM styles inside a loop forces the browser to recompute layout synchronously on every iteration.
- **Verify:** Chrome Performance trace shows repeated purple "Recalculate Style / Layout" warnings inside JS callbacks; check `frontend-layout-thrash` hits.
- **Optimization:** Batch all DOM reads first, then batch all DOM writes (or schedule writes in `requestAnimationFrame`), and animate with `transform`/`opacity` instead of `top`/`left`/`width`/`height`.
- **Tradeoff:** Requires separating read/write passes across helpers or UI components.

### Re-render storms & unstable references
- **Why:** Passing inline object/arrow props (`style={{...}}`, `onClick={() => ...}`) into expensive subtrees, subscribing to coarse global Context/Store slices, or rebuilding derived arrays on every render triggers cascading reconciliations.
- **Verify:** React Profiler / framework devtools show unchanged components re-rendering on unrelated keystrokes or timer ticks.
- **Optimization:** Split high-frequency state (inputs, scroll, hover) down to leaf components or atomic store selectors; memoize heavy derived lists/subtrees only where profiling confirms cost.
- **Tradeoff:** Premature `useMemo`/`React.memo` everywhere adds dependency-tracking overhead and subtle stale-closure bugs.

### Unvirtualized large lists & main-thread long tasks (> 50 ms)
- **Why:** Rendering thousands of DOM nodes spikes layout/paint/memory; synchronous JSON parsing, markdown/syntax highlighting, or sorting > 50 ms blocks input events (high INP).
- **Verify:** DOM node count > 1,500 on one screen or Performance flamegraph shows long yellow Scripting blocks (> 50 ms).
- **Optimization:** Virtualize long lists/tables (render only visible viewport rows + overscan), debounce expensive filters, and move heavy parsing/transforms to Web Workers or chunked idle/scheduler slices.
- **Tradeoff:** Virtualization complicates native browser `Ctrl+F` search and variable-height scroll anchoring.

## 3. Build & CI Pipelines

### Cold dependency installs & missing layer caching
- **Why:** Re-downloading/rebuilding dependencies on every CI run or copying `.` before `package.json`/`pyproject.toml` in a `Dockerfile` busts layer caches on any source edit.
- **Verify:** CI step timing shows `npm ci`/`pip install`/`cargo fetch` taking > 30% of pipeline duration.
- **Optimization:** Cache store directories keyed by lockfile hash (`actions/cache` / BuildKit `--mount=type=cache`), copy manifest+lockfiles before source code in `Dockerfile`, and add `.dockerignore` for `.git`/`node_modules`/artifacts.
- **Tradeoff:** Stale cache keys can mask undeclared system/tool changes; keep lockfile hash strictly in the cache key.

### Unbounded compilation, missing incremental cache & unsharded CI
- **Why:** Running `tsc`, `eslint`, unit tests, and E2E suites serially in one job, generating full sourcemaps on PR checks, or scanning barrel trees with uncached transpilers inflates wall time.
- **Verify:** Compare local `bench-cmd.py` CPU ratio: single-core saturation vs idle wait; inspect `tsc --extendedDiagnostics` or `cargo build --timings`.
- **Optimization:** Enable `tsc --incremental` / Turborepo/Nx remote cache, replace Babel/ts-jest with SWC/esbuild/Vitest where compatible, shard E2E/slow tests across parallel runners, and disable heavy sourcemaps/minification in non-release PR checks.
- **Tradeoff:** Sharding and remote caching add CI runner/storage cost and require deterministic, isolated tests.
