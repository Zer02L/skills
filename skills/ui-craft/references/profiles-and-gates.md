# Profiles, Gates & Review Checklist

Load this reference when resolving lint findings, authoring interactive components (`--scope component`), building app/dashboard screens (`--profile app`), or running a blind finish review.

## 1. Profile comparison

| Dimension | `commercial` (default) | `editorial` | `app` |
| --- | --- | --- | --- |
| Primary goal | Conversion, clear offer, fast trust | Calm typographic hierarchy, restraint | Task throughput, scannability, data density |
| Badges / pills above headings | Allowed when informative (promo, category) | `REFLEX` (`RFX-ED-EYEBROW`) | Avoid decorative pills; use structured labels |
| Tracked uppercase labels | Allowed on micro-meta when readable | `REFLEX` (`RFX-ED-TRACKED-CAPS`) | `REFLEX` on `<th>` and `<label>` |
| CTA arrows (`→`) & status dots | Allowed for directional affordance / live chat | `REFLEX` (`RFX-ED-ARROW-DOT`) | Keep buttons verb-first; dots only for real status |
| Nested cards | Allowed in drawers/calculators if cleanly padded | `REFLEX` (`RFX-ED-CARD-IN-CARD`) | Prefer flat panels + hairline `divide-y` |
| Special invariants | Real proof from brief/DB only | ~80 words/screen rhythm, left-aligned heads | 4 data states, `tabular-nums`, URL-synced filters |

## 2. Gate catalog (enforced by `scripts/ui-lint.py`)

### Tier 1 — `FLOOR` (never ships, cannot be waived)

| ID | What it catches | Why it exists |
| --- | --- | --- |
| `FLR-A11Y-FOCUS` | `outline-none` without `focus-visible:ring`/`outline` | Preserves keyboard navigation (WCAG AA / ГОСТ) |
| `FLR-A11Y-ICON-BTN` | Icon-only `<button>` lacking `aria-label`/`title`/`.sr-only` | Screen readers cannot announce unlabeled SVG buttons |
| `FLR-A11Y-IMG-ALT` | `<img ...>` without `alt=` (`alt=""` allowed) | Ensures accessible images and clean alt fallback |
| `FLR-LYT-OVERFLOW` | Rigid `w-[>360px]` without `max-w-*`, or `w-screen`/`100vw` | Prevents horizontal scrollbars at 320–390px viewports |
| `FLR-LYT-OVERFLOW-CLIP` | `overflow-x: hidden` on `html` or `body` | `hidden` breaks `position: sticky`; `overflow-x: clip` fixes it |
| `FLR-MOT-TRANSITION-ALL` | `transition-all` / `transition: all` | Causes unintended layout/paint transitions |
| `FLR-MOT-LAYOUT-ANIM` | `transition` or `@keyframes` on `width`/`height`/`top`/`left`/`margin`/`padding` | Triggers main-thread layout thrashing |
| `FLR-MOT-HIDDEN-NOJS` | `opacity-0 translate-y-*` without `no-js`/`data-js`/`x-cloak` | Leaves content invisible if scripts fail or stall |
| `FLR-CLR-SLOP-GRADIENT` | `from-indigo/purple/violet` paired with `to-purple/pink/cyan` | Signature default LLM gradient cliché |
| `FLR-CLR-GRADIENT-TEXT` | `bg-clip-text text-transparent` / `background-clip: text` | Lowers contrast and reads as generic template |
| `FLR-TOK-HEX-LITERAL` | `bg-[#...]` Tailwind hex or literal CSS hex outside `:root`/`@theme`/`[data-theme` | Breaks theming and token single-source-of-truth |
| `FLR-DOM-INLINE-COLOR` | Inline `style="color: #..."` (CSS vars like `--accent: #...` allowed) | Leaks un-themed literals into markup |
| `FLR-CPY-CLICHE` | Empty EN/RU buzzwords (*инновационные решения*, *supercharge your*, etc.) | Replaces substance with LLM filler |
| `FLR-CPY-FAKE-PROOF` | `lorem ipsum`, `Acme Corp`, `John Doe`, fake `10,000+` stats | Prevents shipping placeholder or invented trust claims |

### Tier 2 — `REFLEX` (default LLM tics; waivable with concrete reason)

| ID | Profiles | What it catches |
| --- | --- | --- |
| `RFX-CLR-BLUR-ORB` | all | `blur-2xl`/`blur-3xl` or CSS `blur(>=40px)` decorative blobs |
| `RFX-CLR-GLASS-STACK` | all | `backdrop-blur-*` paired with `bg-white/N` / `bg-black/N` |
| `RFX-CLR-RAW-GRAY` | all | Raw `bg-gray-*`/`slate`/`zinc`/`neutral`/`stone` instead of tokens |
| `RFX-MOT-SLOW` | all | `duration-500/700/1000` or CSS transitions `>= 0.5s` |
| `RFX-LYT-CRAMPED-RADIUS` | all | `rounded-2xl/3xl` paired with tight `p-1..p-3` |
| `RFX-TYP-ITALIC-HEADING` | all | Single `<em>`/`<i>` emphasis inside `<h1>`–`<h3>` |
| `RFX-DOM-EMOJI-ICON` | all | UI emojis (`🚀✨🔥💡⚡🎯✅💎`) inside headings/buttons/links/nav |
| `RFX-ED-EYEBROW` | `editorial` | Badge/pill directly above `<h1>`–`<h3>` |
| `RFX-ED-TRACKED-CAPS` | `editorial`, `app` (`th`/`label`) | `uppercase` + `tracking-wide/wider/widest` |
| `RFX-ED-ARROW-DOT` | `editorial` | Arrows (`→`) inside CTA, pulsing dots, or chained `·` meta strings |
| `RFX-ED-CARD-IN-CARD` | `editorial` | Nested bordered card inside another card |

### Tier 3 — `FINISH` (craft checks; warn by default, fail under `--strict`)

- `FIN-MOT-REDUCED`: CSS has motion without `@media (prefers-reduced-motion: reduce)`.
- `FIN-TYP-TABULAR`: `<table>` or metric/price block missing `tabular-nums`.
- `FIN-IMG-ATTRS`: Non-hero `<img>` missing `loading=` or `decoding=`.
- `FIN-APP-STATES` (`app`): Dynamic list/table lacking `loading`/`empty`/`error` states.

## 3. Waiver syntax

Suppress a justified `REFLEX` finding via a comment on the same line, immediately above it, or in the first 50 lines (file-wide):

```html
<!-- ui-craft-waive: RFX-CLR-GLASS-STACK (Sticky nav over map canvas needs frosted backdrop) -->
```

Rules: reasons must be at least 4 characters explaining *why*. Attempting to waive a `FLOOR` rule is rejected by `ui-lint.py`.

## 4. State checklists (`app` & `component` scopes)

- **4 data states (every async region in `app`):**
  1. `loading` — structural skeleton matching the incoming layout (never a lonely spinner).
  2. `empty` — states what belongs there plus the primary creation/import action.
  3. `error` — explains what failed and offers an explicit retry control.
  4. `full` — realistic density, `tabular-nums` on numbers, URL-synced filters/tabs.
- **8 control states (`--scope component` or design systems):** `default`, `hover`, `:focus-visible`, `:active`, `disabled`, `loading`, `error`, `success`.

## 5. Blind fresh-context review checklist

When launching a fresh-context subagent, pass only rendered markup/screenshots + the brief — **never** the builder's plan or excuses:

1. **Pass 0 — Brief fit (anti-template test):** Does this layout answer *this* product and job, or could it be dropped onto any site in the category? Generic framing detached from the brief ranks as a high-severity finding even if `ui-lint.py` passes.
2. **Hero / Shell & mobile pass:** Verify the first viewport states what is offered, for whom, and renders its primary visual or control cleanly at `1280px` and `390px` (plus dark theme if shipped).
3. **Evidence & waiver discipline:**
   - Every finding cites a concrete screenshot, DOM metric, or source line — **no predicted passes** and no predicted failures.
   - Re-verify every `ui-craft-waive` independently; rank findings by user impact rather than ease of fixing, and never soften a broken breakpoint as "nearly there".
4. **Two-layer verification (`static` vs `visual`):**
   - **Static (always required):** `ui-lint.py lint` (plus `kept` on redesigns).
   - **Visual (when a preview/browser exists):** Inspect `1280px` and `390px` (plus dark theme if shipped) and optionally evaluate `assets/dom-audit.js` via `preview_evaluate` or Playwright `page.evaluate`. Report `visual: not run` when no browser is available, or `visual: incomplete` if desktop was checked without `390px` (or shipped dark mode) — never `pass`.
5. **Visual diagnosis ("You see → You do"):**

| You see | You do |
| --- | --- |
| Horizontal scroll at `390px` (`horizontalOverflow`) | Replace rigid `w-[>360px]`/`100vw` with `max-w-full`, wrap tables in `overflow-x-auto`, keep `overflow-x: clip` on `html`/`body` |
| Metric or price unit breaks onto a second line (`wrappedUnits`) | Add `whitespace-nowrap` on numeric+unit pairs or move the unit to the label above |
| Icon or chip squishes next to flex text (`squeezed-icon`) | Add `shrink-0` (`flex-shrink: 0`) on icons, badges, and avatars inside flex rows |
| Container bottom padding looks clipped (`container-block-inset`) | Remove conflicting fixed height / `overflow-y: hidden` on inner wrapper or carry bottom padding inside the scrollable/clipped frame |
| Button/chip label hugs one edge (`control-edge-inset`) | Use symmetric padding or move trailing badge/icon into a separate container gap |
| Broken image or unintentional empty pane void (`brokenImages`) | Fix asset path/fallback or fill the section cleanly instead of leaving hollow vertical space |
