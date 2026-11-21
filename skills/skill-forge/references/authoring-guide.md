# Skill Authoring & Optimization Guide

Load this reference while designing a new skill, squeezing token overhead out of an existing CLI/API workflow, or authoring `hook-triggers.json`.

## 1. Writing rules that generalize

- **Explain the *why*:** Tell the model why a rule exists (`"crossAlign has no 'stretch' mode in FigCraft; use sizingH: 'fill' on children so batch calls do not roll back"`) rather than spamming `ALWAYS`/`NEVER`.
- **Use imperative instructions + one minimal working example:** One 10-line runnable snippet beats three abstract paragraphs.
- **Avoid overfitting:** Do not hardcode specific test prompts or machine-specific home paths inside `SKILL.md` or bundled scripts. Skills should remain valid after being copied into `~/.skills-manager/skills/<name>/`.
- **Keep `SKILL.md` lean:** Move full CLI flag tables, JSON schemas, and secondary setup flows (like MCP/GUI configuration) into `references/`. Keep `SKILL.md` focused on the primary path and hard pitfalls.

## 2. Optimizing CLI / sandboxed tools (`Probe -> Optimize -> Measure`)

Before drafting instructions for a CLI, Flatpak, Docker, or REST-backed tool:

1. **Measure the raw baseline first:**
   - Check how big `--help`, `commands`, or MCP `tools/list` schemas are. Never let an agent dump a 100 KB command catalog into context when a `lookup "<query>" --limit N` wrapper returns 5 KB.
   - Check startup penalties (e.g., system font indexing, plugin discovery, cold JVM/container boot). Default to fast deterministic flags (`--no-system-fonts`, `--json`, `--quiet`).
   - Check sandbox boundaries (Flatpak `--filesystem`, Docker `-v`, read-only roots) so the wrapper mounts caller paths automatically instead of failing on turn 1.
2. **Collapse N turns into 1 atomic script call:**
   - Prefer stdin JSON/JSONL batching (`run`) with step references (`$ref`) over sequential one-layer-per-turn calls.
   - Add a `--compact` output mode that keeps only `id`, `path`, `bytes`, `ok`, and `error` instead of returning huge nested object trees after every mutation.
3. **Measure the finished skill on real inputs:**
   - Run `scripts/audit-skill.py --strict <skill-dir>` to verify idle/active token budgets.
   - Measure actual before/after latency, payload bytes, and tool round-trips on a representative task.

## 3. Authoring universal `hook-triggers.json`

Add `hook-triggers.json` only when semantic triggering via `description` is insufficient or when specific shell commands must be blocked deterministically.

### Portability rules (Python `re` + JS `RegExp`)

Because cross-agent hooks run in both Python (`skill-hook-router.py`) and JavaScript (`opencode` plugin):

- **Never use inline regex flags** like `(?i)`, `(?m)`, or `(?s)` — JS `RegExp` throws a `SyntaxError`. Set `"case_insensitive": true` at the rule root instead.
- **Never use `\b` around Cyrillic (or non-ASCII) words:** JS `\b` only recognizes `[A-Za-z0-9_]` as word characters, so `\bскил\b` silently fails in JS while matching in Python. Use explicit boundaries instead:
  - Leading: `(?:^|[^\wа-яёА-ЯЁ])`
  - Trailing: `(?=$|[\s,.;:!?()'"/-])`
- **Always provide an escape hatch for `deny_shell`:** Use `"allow_if_regex"` when a wrapper script legitimately wraps or cites the guarded command, and mention `SKIP_SKILL_HOOKS=1` in `"reason"`.
- **Always add near-miss tests** in `evals/trigger-tests.json` and run `scripts/test-triggers.py <skill-dir> --live-router --js-check` before syncing hooks.
