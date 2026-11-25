---
name: ui-craft
description: Universal anti-slop UI design standard, layout dealer, and zero-Node linter across commercial, editorial, and app profiles. Use when designing, building, auditing, or redesigning web pages, dashboards, or components in HTML, CSS, Templ, React, Vue, Svelte, Astro, or Tailwind. Exclude Figma/FigCraft file edits, spring motion tuning, or backend bottlenecks.
compatibility: Python 3 stdlib
---

# UI Craft

Zero-dependency web UI standard that replaces conflicting style guides with **one deterministic Python engine** (`scripts/ui-lint.py` + `scripts/ui-deal.py`) and three explicit profiles.

## 1. Choose one profile

| Profile | Use for | Key rule differences |
| --- | --- | --- |
| `commercial` (default) | B2B/B2C sites, e-commerce, SaaS marketing | Allows intentional badges, CTA arrows, status dots, real DB/brief stats; blocks generic AI slop & broken a11y |
| `editorial` | Essays, studios, architectural/craft sites | Enforces strict minimalist discipline: no eyebrows, tracked uppercase, CTA arrows, or card-in-card |
| `app` | Dashboards, admins, settings, tables, forms | Drops hero/word-count marketing rules; enforces dense controls, `tabular-nums`, and 4 data states |

## 2. Five-stage workflow

1. **Pre-flight (always first):** Run `python3 scripts/ui-lint.py preflight [DIR]` to detect framework, CSS `:root`/`@theme` tokens, self-hosted vs CDN fonts, and `DESIGN.md`/`AGENTS.md`. Preserve the project's existing tokens, font policy (never inject external CDNs into Zero-CDN repos), and markup conventions.
2. **Deal or Snapshot:**
   - **New build:** Run `python3 scripts/ui-deal.py deal --profile <p> --material <m> --job <j>` to pick a macrostructure, hero/shell posture, and material direction clear of `.ui-craft/log.json`.
   - **Redesign / Polish:** Run `python3 scripts/ui-lint.py snapshot <PATHS> --out .ui-craft/before.json` before editing so no route, form field, HTMX/event handler, or `data-*` hook is lost.
3. **Build hero or shell first:** Establish semantic tokens, nav/shell, and the first viewport (or app table/toolbar) cleanly before adding lower sections. Keep copy grounded in real project facts; read `references/layouts-and-compositions.md` when composing multi-section pages.
4. **Lint, Waive, & Verify Wiring:**
   - Run `python3 scripts/ui-lint.py lint <PATHS> --profile <p>` and fix all `FLOOR` and open `REFLEX` findings.
   - `FLOOR` rules never ship and cannot be waived. `REFLEX` findings may be suppressed with a concrete inline/header comment (`/* ui-craft-waive: RFX-... (reason) */`); `FINISH` checks guide craft and fail only under `--strict`.
   - On any redesign, run `python3 scripts/ui-lint.py kept <PATHS> --before .ui-craft/before.json` and fix unexpected drops (or document intentional removals via `--allow-drop`).
5. **Fresh-Context Review & Log:** Run a blind subagent review (or cold self-audit if single-agent) using the checklist in `references/profiles-and-gates.md` (and optionally run `assets/dom-audit.js` in a live preview/browser), then log new builds via `python3 scripts/ui-deal.py log ...`.

## 3. Universal Floor (never waived)

- **Tokens:** All UI colors go through `:root`/`@theme` custom properties; avoid raw hex/rgb literals outside token blocks or inline `style="color: ..."`.
- **Accessibility:** Never strip `outline` without `:focus-visible`; every `<img ...>` needs `alt=`; icon-only `<button>` needs `aria-label` or `.sr-only`.
- **Layout & Motion:** Never `transition-all` or animate `width`/`height`/`top`/`left`; use `overflow-x: clip` on `html`/`body`; avoid rigid `w-[>360px]` without `max-w-*` or `100vw`; never hide initial content behind `opacity-0 translate-y-*` without a no-JS fallback.
- **Honest Visuals & Copy:** Ban indigo/purple AI gradients, gradient-clipped headings, lorem/invented social proof, and LLM cliché phrases.

## 4. Bundled scripts (relative to this skill directory)

```bash
python3 scripts/ui-lint.py preflight .
python3 scripts/ui-deal.py deal --profile commercial --material product --job buy
python3 scripts/ui-lint.py lint src/ui --profile commercial
python3 scripts/ui-lint.py snapshot src/ui --out .ui-craft/before.json
python3 scripts/ui-lint.py kept src/ui --before .ui-craft/before.json
```

## 5. Progressive disclosure references & assets

- `references/profiles-and-gates.md` — full Floor/Reflex/Finish gate table, waiver syntax, 4 data + 8 control states, and blind review checklist.
- `references/layouts-and-compositions.md` — 14 macrostructures, 17 section patterns (with Tailwind v4 semantic token grids), and typography/rhythm discipline.
- `references/redesign-and-preflight.md` — pre-flight signal hierarchy, redesign depths (`polish` / `restyle` / `full`), and `snapshot`/`kept` contract guide.
- `assets/dom-audit.js` — optional read-only browser DOM geometry snippet (`preview_evaluate` / Playwright) for overflow, clipped containers, squeezed icons, wrapped units, and broken images.
