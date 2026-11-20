# Live GUI & MCP Setup (Flatpak)

Use headless `scripts/fc.sh run` for one-shot creation, edits, exports, and code inspection. Only use MCP when:
- You want to watch and edit an **open FigCraft GUI window** live (`--control` / `--attach`).
- You need interactive canvas gestures (`pointer`, `key`, `type_text`) or live comment polling (`wait_for_changes`).

Note: FigCraft's MCP server exposes 19 tools (~32.5 KB schema + ~1.6 KB instructions ≈ 8.5K tokens loaded every turn while connected), whereas `SKILL.md` + `scripts/fc.sh` loads only when triggered.

## 1. Attach to a live FigCraft GUI window

Start FigCraft with a control port and explicit automation roots for the directories you want the app to access:

```bash
scripts/fc.sh --mount "$PWD" gui --control 7979 \
  --automation-read-root "$PWD" \
  --automation-write-root "$PWD" \
  path/to/design.figcraft
```

Attach MCP to the running window (do not pass `--automation-*-root` to `--attach`; it inherits the app's roots):

```bash
scripts/fc.sh mcp --attach 7979
```

## 2. Optional `.mcp.json` configuration

For a project that intentionally uses FigCraft MCP:

```json
{
  "mcpServers": {
    "figcraft": {
      "command": "flatpak",
      "args": [
        "run",
        "--filesystem=.",
        "--command=figcraft-cli",
        "ai.storyteller.figcraft",
        "mcp",
        "--no-system-fonts"
      ]
    }
  }
}
```

Replace `"--filesystem=."` with an absolute project path if your MCP client does not expand relative paths, or append `"--attach", "7979"` to connect to a running GUI launched with `--control 7979`.

## 3. Permanent Flatpak overrides (optional)

By default `ai.storyteller.figcraft` only accesses `xdg-documents` and `xdg-pictures`. `scripts/fc.sh` grants per-run `--filesystem=...` access automatically, so global overrides are unnecessary. If you want the GUI desktop app itself to open/save anywhere under `~/Projects` without per-launch flags:

```bash
flatpak override --user --filesystem=~/Projects ai.storyteller.figcraft
```
