# Pre-flight & Safe Redesign Workflow

Load this reference before modifying an existing page, component, or design system.

## 1. Pre-flight signal priority

Run `python3 scripts/ui-lint.py preflight [DIR]` first and honor signals in strict order:

1. **Locked spec (`DESIGN.md` / `design.md` / root `AGENTS.md`):** Overrides generic direction picks. Follow project contracts (e.g., `*.templ` + `templ generate`, DOM source mapping attributes, or build exclusions).
2. **Existing tokens & presets:** Read `:root`, `@theme`, `[data-theme]`, and project config JSONs (`presets/*.json`) as data. Map new sections onto existing semantic variables (`--color-surface`, `--color-content`, `--color-accent`, `--radius-card`, etc.) rather than inventing competing names.
3. **Font delivery policy:** If `preflight` reports `self-hosted`, keep all new typography within the bundled `@font-face` families and never add third-party CDN `<link>` tags without explicit user approval.
4. **Framework conventions:** Match the repo's templating, reactivity, and styling stack (Go Templ + Tailwind v4, React/Next, Vue, Svelte, Astro, Alpine.js, HTMX) without introducing Node/JS build steps into Zero-Node repos.

## 2. Three redesign depths

Ask or confirm which depth fits the user's request before touching files:

| Depth | What changes | What stays untouched |
| --- | --- | --- |
| `polish` | Fix `FLOOR` and open `REFLEX` issues in place (tokens, focus rings, contrast, spacing, motion durations, copy clichés) | Section order, layout grid, routing, handlers |
| `restyle` | Swap palette, surface ladder, typography posture, and component surfaces across the page | Macrostructure, section sequence, all content & wiring |
| `full` | Deal a new macrostructure and section rhythm from the visitor's job and real material | 100% of functional wiring, forms, endpoints, and test hooks |

## 3. Functional preservation contract (`snapshot` -> `kept`)

Never ship a redesign that silently drops a link, form endpoint, input name, HTMX call, event handler, or test/inspector hook.

1. **Capture baseline before editing:**
   ```bash
   python3 scripts/ui-lint.py snapshot path/to/ui --out .ui-craft/before.json
   ```
   Extracts sorted sets of:
   - `links` (`href="..."`)
   - `forms` (`<form method action>`)
   - `htmx_endpoints` (`hx-get`, `hx-post`, `hx-put`, `hx-patch`, `hx-delete`)
   - `inputs` (`<input|select|textarea name="...">`)
   - `test_hooks` (`data-testid`, `data-component`, `data-source`, `data-field`, `data-block`)
   - `handlers` (`hx-trigger`, `x-model`, `x-on:*`, `@*`, `onClick`, `onSubmit`)
   - `headings` (`h1`/`h2` text — tracked for awareness, never blocks a copy improvement)

2. **Refactor and lint:**
   ```bash
   python3 scripts/ui-lint.py lint path/to/ui --profile commercial
   ```

3. **Verify zero broken wiring:**
   ```bash
   python3 scripts/ui-lint.py kept path/to/ui --before .ui-craft/before.json
   ```
   - Exit `0`: all functional bindings survived.
   - Exit `1`: lists every dropped item under `[DROPPED] category: item`. Restore missing wiring before finishing.
   - If the user explicitly asked to remove a legacy route, field, or handler, pass `--allow-drop <item>` (repeatable) and state the intentional removal in your summary.

## 4. Handoff discipline

Report the concrete verification summary at the end of a build or redesign:
- Active profile & scope (`commercial` / `editorial` / `app`).
- Exact `ui-lint.py lint` line (`Floor X FAIL · Reflex Y (Z waived) · Finish W`), listing every waiver and its reason.
- Exact `ui-lint.py kept` status on redesigns (including any `--allow-drop` items).
- Visual verification status: `visual: verified (1280px, 390px[, dom-audit])`, `visual: incomplete (missing 390px/theme)`, or `visual: not run (no browser available)`.
