# Layouts, Macrostructures & Compositions

Load this reference when designing a multi-section page or translating a `ui-deal.py` pick into templates and CSS.

> **Token rule:** The class names below (`bg-surface`, `bg-surface-muted`, `text-content`, `text-content-muted`, `text-accent`, `border-content/10`, `rounded-card`) are illustrative semantic placeholders. Always substitute the exact token utilities discovered by `scripts/ui-lint.py preflight`.

## 1. Fourteen macrostructures (page architectures)

| Slug | Profiles | Best materials | Structural flow |
| --- | --- | --- | --- |
| `bento-grid` | `commercial`, `editorial` | `product`, `photo`, `data` | Offer Hero → Asymmetric Bento (8/4 or 7/5) → Spec Table → Action |
| `split-studio` | `commercial`, `editorial` | `photo`, `product` | 60/40 Split Hero → Showcase → Hairline Rows → Form |
| `workbench` | `commercial`, `app` | `product`, `data` | Live UI/Control Hero → Interactive Switcher → Steps → Offer |
| `catalogue` | `commercial` | `photo`, `product` | Filter/Search Hero → Storefront Grid → Offer/Drawer → Form |
| `narrative-workflow` | `commercial`, `editorial` | `photo`, `product`, `words` | Outcome Hero → Numbered Steps → Sticky Proof → Intake Form |
| `feature-stack` | `commercial`, `editorial` | `product`, `photo` | Full-Width Showcase → Sticky Narrative + Media → Figures → Offer |
| `stat-led` | `commercial`, `editorial` | `data`, `words` | Verified Fact Statement → Figures Row → Comparison Table → Form |
| `photographic` | `editorial`, `commercial` | `photo` | Edge-to-Edge Hero Frame → Split → Horizontal Rail → Booking Form |
| `long-document` | `editorial` | `words`, `data` | Thesis Statement → Prose + Hairline Facts → Rows → Signature/Form |
| `manifesto` | `editorial` | `words` | Oversized Display Thesis → Contrasting Band → Rows → Single Action |
| `index-first` | `editorial`, `app` | `words`, `data` | Structured Directory Index → Rows → Comparison Table → Contact |
| `conversational-faq` | `commercial`, `editorial` | `words`, `product` | Direct Split → Visible Q&A Rows (no tiny accordions) → Table → Form |
| `table-workspace` | `app` | `data`, `product` | Top Toolbar + Filters → Tabular Grid → Inline/Detail Switcher |
| `master-detail` | `app` | `data`, `words`, `product` | Record Queue Index → Split Inspector + Schedule/Rows |

## 2. Seventeen composable sections (Tailwind v4 skeletons)

Mix 3–6 distinct compositions per page. Never place two identical section structures back-to-back.

1. **Split (50/50 or 60/40):** `grid grid-cols-1 lg:grid-cols-12 gap-8 items-center` (`lg:col-span-5` copy + `lg:col-span-7` visual).
2. **Showcase (16:9 / 21:9):** `max-w-7xl mx-auto px-4` with wide media frame (`aspect-video lg:aspect-21/9 overflow-hidden rounded-card`) and 2-column caption/spec row below.
3. **Grid (equal entities):** `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6` (`flex flex-col justify-between`). Use for homogeneous items (catalog SKUs, team, gallery) — avoid as a generic feature dump.
4. **Bento (asymmetric mosaic):** `grid grid-cols-1 md:grid-cols-12 gap-4 lg:gap-6` with anchor tile `md:col-span-8 md:row-span-2` and supporting `md:col-span-4` tiles.
5. **Rows (hairline list):** `divide-y divide-content/10 border-y border-content/10`, row `py-6 grid grid-cols-1 lg:grid-cols-12 gap-4 items-baseline`.
6. **Table (comparison/spec):** `w-full text-left border-collapse text-sm` with `py-4 px-4 border-b border-content/10 tabular-nums`. Wrap in `overflow-x-auto`.
7. **Figures (verified metrics):** `grid grid-cols-2 lg:grid-cols-4 gap-8 divide-y lg:divide-y-0 lg:divide-x divide-content/10` with `tabular-nums`. Every number must come from brief or DB.
8. **Steps (sequential process):** `grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6` with explicit ordinal and deliverable per step.
9. **Statement (typographic thesis):** `py-20 max-w-4xl mx-auto px-4` with `text-2xl md:text-4xl lg:text-5xl font-semibold tracking-tight leading-snug`.
10. **Band (surface shift):** `w-full bg-surface-muted border-y border-content/10 py-16 px-4` — marks a thematic break once or twice per page.
11. **Form (split intake):** `grid grid-cols-1 lg:grid-cols-12 gap-12 max-w-6xl mx-auto` (`lg:col-span-5` trust/SLA context, `lg:col-span-7` labeled fields).
12. **Rail (horizontal snap strip):** `flex gap-6 overflow-x-auto snap-x snap-mandatory pb-4` with `snap-start shrink-0 w-[280px] sm:w-[340px]`.
13. **Pinned (sticky narrative):** `grid grid-cols-1 lg:grid-cols-12 gap-12` (`lg:col-span-5 lg:sticky lg:top-24 self-start` + `lg:col-span-7 space-y-12`).
14. **Switcher (tabbed comparison):** Accessible `role="tablist"` / `role="tab"` + segmented pill container, preserving URL or interactive state cleanly.
15. **Index (dense directory):** Compact `min-h-12` hairline rows with aligned columns for docs, archives, or queues.
16. **Schedule (time slots/timeline):** `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-7 gap-3` or vertical agenda rows with `tabular-nums`.
17. **Offer (decision anchor):** `max-w-4xl mx-auto p-8 rounded-card border border-content/15 bg-surface` combining real image/scope, exact price, primary CTA, and warranty/terms.

## 3. Bento composition discipline (`commercial` / `editorial`)

When using `bento-grid` (`app` dashboards should prefer uniform scannable tables and KPI strips instead):

- **Mix tile kinds in checkerboard contrast:** Alternate hero UI/visual tiles, single isolated controls, verified stats/statements, and diagrams/collections — never pack identical feature cards side by side.
- **Say each thing once:** Never repeat the same metric, user name, or UI chrome across multiple tiles in one grid.
- **Anchor one focal tile:** Give interactive or visual emphasis to a single lead tile and keep neighboring tiles calm.
- **Recompose natively at `390px`:** Stack or adjust tile grids for mobile widths instead of scaling down a desktop canvas.
- **Faux-UI delegation:** If a hero or bento tile needs a miniature mocked product UI or animated cursor walkthrough, delegate that illustration to the `stageshow` skill while keeping page layout, tokens, and gating under `ui-craft`.

## 4. Rhythm, Typography & Font Discipline

- **Container & gutters:** Cap page content measure (`max-w-6xl` or `max-w-7xl mx-auto`), align vertical section edges consistently, and keep at least 35% of cards/bands visually distinct in density.
- **Scale & alignment:** Body copy `>= 16px` (`text-base`), headings step cleanly (`h1` 1.8–3x body; avoid orphan 1-word italic highlights), and prefer left-aligned section headers over endless centered stacks.
- **Cyrillic & Zero-CDN safety:** Check `preflight` font output before picking a typeface. When a repo uses self-hosted `.woff2` fonts (Zero-CDN) or serves Cyrillic content, stay on the repo's verified font stack (`font-sans` / `font-serif-title` / `font-mono`) rather than injecting unverified Latin-only Google Fonts or Fontshare links.
- **Visual hierarchy:** One primary CTA style per viewport; reserve the accent color for primary actions, active selections, and `:focus-visible` rings.
- **Concentric radii & even insets:** Keep `outerRadius = innerRadius + padding` on nested shapes, and carry container padding evenly around the bottom edge as well as top and sides.
- **No wrapped units or squeezed icons:** Keep numeric values with units (`99.9%`, `14 ms`, `12 400 ₽`) on one line via `whitespace-nowrap`; add `shrink-0` on icons, avatars, and badges inside flex rows.
- **Opaque layering & authentic marks:** Avoid stacking semi-transparent surfaces (`onion skin`); use the product's real mark or a clean typographic wordmark rather than an invented single-letter colored square (in `commercial`/`editorial`; workspace monograms remain fine in `app`).
- **Restrained AI chrome:** Avoid decorative sparkle/wand icons or violet glow as generic AI ornament unless it is the product's own established icon.
