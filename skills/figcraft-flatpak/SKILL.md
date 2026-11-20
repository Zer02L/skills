---
name: figcraft-flatpak
description: Create, edit, inspect, export, convert, or generate code from UI designs and prototypes using Flatpak FigCraft (ai.storyteller.figcraft, figcraft-cli). Use whenever working with .figcraft, .fig, .penpot, or .sketch design files, building auto-layout frames, components, design tokens/variables, or attaching to a running FigCraft GUI window.
compatibility: Linux with Flatpak ai.storyteller.figcraft and Python 3
---

# FigCraft (Flatpak)

Use `scripts/fc.sh` (relative to this skill directory) instead of raw `flatpak run` or an always-on MCP server. It automatically mounts Flatpak `--filesystem` paths, defaults to `--no-system-fonts` (faster and deterministic), reads JSON/JSONL scripts from stdin, and bounds command lookups.

## 1. One-shot batch workflow (preferred)

Build an entire screen, save `.figcraft`, and export a PNG preview in **one** `scripts/fc.sh run` call using `"as"` and `{"$ref": "..."}` (executes as one atomic undo step; rollback on error):

```bash
scripts/fc.sh run --out screen.figcraft --compact <<'EOF'
[
  {"command": "frame.create", "as": "root", "params": {
    "name": "Card", "x": 0, "y": 0, "width": 360, "height": 220,
    "props": {"fill": "#0F172A", "cornerRadius": 16, "layout": "vertical", "gap": 12, "padding": 24, "mainAlign": "center", "crossAlign": "min"}
  }},
  {"command": "text.create", "params": {
    "name": "Title", "text": "Ready", "parent": {"$ref": "root"},
    "props": {"fontSize": 22, "fill": "#F8FAFC", "sizingH": "fill"}
  }},
  {"command": "file.export", "params": {
    "ids": [{"$ref": "root"}], "format": "png", "scale": 2, "path": "preview.png"
  }}
]
EOF
```

- Pass `--in existing.figcraft` to edit an existing file.
- Pass `--compact` to return condensed JSONL lines (`step`, `command`, `ok`, `id`/`path`/`bytes`/`error`) instead of full node payloads.

## 2. Exact FigCraft syntax rules (avoid rollback loops)

- **Coordinates:** 1 unit = 1 px; x right, y DOWN. `x`/`y` are relative to the parent frame (groups do not count).
- **Auto-layout:** `layout`: `"vertical"` | `"horizontal"` | `"grid"`.
  - `padding`: single number `24` or 4-tuple `[t, r, b, l]` (never a 2-element array).
  - `mainAlign`: `"min"` | `"center"` | `"max"` | `"spaceBetween"` | `"spaceAround"` | `"spaceEvenly"`.
  - `crossAlign`: `"min"` | `"center"` | `"max"` | `"baseline"` (**never `"stretch"`** — stretch children with `sizingH: "fill"` / `sizingV: "fill"`).
- **Paints:** `fill: "#RRGGBB"` (or `"#RRGGBBAA"`, `{"$var": "token"}`, `"none"`, `null`), `stroke: "#..."`, `strokeWeight`.
- **Flatpak sandbox:** `ai.storyteller.figcraft` only mounts `xdg-documents` and `xdg-pictures` by default. `fc.sh` auto-mounts parent directories of CLI args and file `"path"` params; pass `--mount DIR` before the subcommand for extra directories.
- **Fonts:** `--no-system-fonts` is on by default (faster startup and cross-machine layout). Pass `--system-fonts` before the subcommand only when installed system fonts are specifically needed.
- **Never dump all 645 commands** (`figcraft-cli commands` is ~118 KB text / ~190 KB JSON). Always use `scripts/fc.sh lookup "<term>"`.

## 3. Command quick reference (`scripts/fc.sh`)

| Subcommand | Purpose |
| --- | --- |
| `run [--in F] [--out F] [--compact] [SCRIPT\|-]` | Execute JSON/JSONL command script in one headless session |
| `info <FILE>` | Inspect pages, node count, top-level frames, styles, variables as JSON |
| `render <FILE> --out <OUT.png> [opts]` | Render the whole first/specified page with background |
| `export <FILE> --out <OUT> [opts]` | Export frames/layers/file (`png`, `jpg`, `svg`, `webp`, `pdf`, `xml`, `fig`, `penpot`) |
| `convert <IN> <OUT>` | Convert by extension (`.figcraft`, `.json`, `.svg`, `.png`, `.pdf`, `.fig`, `.penpot`) |
| `lookup <QUERY> [--limit N]` | Search commands safely (default cap 25 matches) |
| `inspect-code <FILE> [--node ID\|NAME] [--lang L]` | Generate `css`, `html`, `react`, `tailwind`, `vue`, `swiftui`, `compose`, `flutter`, etc. |
| `gui [--control PORT] [FILE]` | Launch FigCraft GUI (optional control port for `--attach`) |
| `mcp [--attach PORT]` | Start stdio MCP (only when driving an interactive GUI or watching comments) |
| `raw <figcraft-cli args...>` | Pass through directly to `figcraft-cli` with `--mount` / font flags |

## 4. Visual verification

For any visual UI task, include `file.export` (PNG, `scale: 1` or `2`) inside your `run` script or call `scripts/fc.sh render`, then inspect the generated PNG image to catch clipping, text truncation, contrast, or overlap issues before finishing.

## 5. Additional references (read only when needed)

- `references/commands-cheatsheet.md` — styles, variables/tokens, components & variants, gradients, vectors, prototyping, and `node.set` keys.
- `references/live-mcp.md` — attaching to a live FigCraft GUI window (`--control`), `.mcp.json` setup, and permanent `flatpak override` permissions.
