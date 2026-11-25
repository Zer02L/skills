# Skill Authoring & Optimization Guide

Load this reference while designing a new skill, squeezing token overhead out of an existing CLI/API workflow, or authoring `hook-triggers.json`.

## 1. Writing rules that generalize

- **Explain the *why*:** Tell the model why a rule exists (`"crossAlign has no 'stretch' mode in FigCraft; use sizingH: 'fill' on children so batch calls do not roll back"`) rather than spamming `ALWAYS`/`NEVER`.
- **Use imperative instructions + one minimal working example:** One 10-line runnable snippet beats three abstract paragraphs.
- **Avoid overfitting:** Do not hardcode specific test prompts or machine-specific home paths inside `SKILL.md` or bundled scripts. Skills should remain valid after being copied into `~/.skills-manager/skills/<name>/`.
- **Spot repeated work across test runs (Repeated Work Detection):** Inspect transcripts of test executions. If agents independently write identical Python/bash one-liners, custom `curl`/`jq` wrappers, or repeated boilerplate, do not leave it to the agent's creativity — bundle that deterministic code into `scripts/` once.
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

## 3. Structuring bundled scripts & assets (standalone portability)

Skills Manager copies each skill directory independently, and skills may be installed directly from a Git subdirectory URL:

- **Zero repo-root imports or personal paths:** Never import from repo-root `scripts/` or `scripts/lib/`, and never hardcode local user home directories in `SKILL.md` or `scripts/`.
- **Internal Python modules (`scripts/_*.py`):** When a skill script or rule catalog grows large, split shared schemas or rule tables into `scripts/_spec.py` or `scripts/_rules.py`. `audit-skill.py` automatically excludes `_*` files from CLI script counts and executable-bit checks while still auditing their portability.
- **Avoid heredoc Python & inline HTML/JS:** Do not embed multi-hundred-line Python inside `.sh` heredocs or large HTML/CSS/JS inside Python f-strings. Put implementation in `scripts/_impl.py` behind a thin 5-line `.sh` compatibility shim, and move templates into `assets/`.
- **Test standalone copies:** Verify bundled scripts in a `TemporaryDirectory` via `shutil.copytree` outside the repository so missing internal imports or asset paths fail immediately.

## 4. Authoring universal `hook-triggers.json`

Add `hook-triggers.json` only when semantic triggering via `description` is insufficient or when specific shell commands must be blocked deterministically. Whenever `enabled` is `true`, include `evals/trigger-tests.json` (checked by `scripts/audit-skill.py` and `./scripts/check.py`).

### Portability rules (Python `re` + JS `RegExp`)

Because cross-agent hooks run in both Python (`skill-hook-router.py`) and JavaScript (`opencode` plugin):

- **Never use inline regex flags** like `(?i)`, `(?m)`, or `(?s)` — JS `RegExp` throws a `SyntaxError`. Set `"case_insensitive": true` at the rule root instead.
- **Never use `\b` around Cyrillic (or non-ASCII) words:** JS `\b` only recognizes `[A-Za-z0-9_]` as word characters, so `\bскил\b` silently fails in JS while matching in Python. Use explicit boundaries instead:
  - Leading: `(?:^|[^\wа-яёА-ЯЁ])`
  - Trailing: `(?=$|[\s,.;:!?()'"/-])`
- **Always provide an escape hatch for `deny_shell`:** Use `"allow_if_regex"` when a wrapper script legitimately wraps or cites the guarded command, and mention `SKIP_SKILL_HOOKS=1` in `"reason"`.
- **Always add near-miss tests** in `evals/trigger-tests.json` and run `scripts/test-triggers.py <skill-dir> --live-router --js-check` before syncing hooks.

## 5. Designing trigger queries and near-misses

Whether tuning `description` or writing `evals/trigger-tests.json`:

- **Realism over keywords:** Draft prompts with natural noise, conversational context, file paths, or typos (e.g., `"my boss sent me sales.xlsx and wants margin in col D"` instead of `"Format spreadsheet"`). Include cases where the user describes the intent without knowing the tool's exact name.
- **Genuine near-misses over trivial negatives:** The most valuable `should_not_trigger` tests are adjacent tools or overlapping vocabulary (e.g. `manage-skills list` vs `skill-forge`, or `git commit` vs git-rebase tool). Avoid trivial negatives like `"Write a fibonacci function"` — they create false confidence without testing boundary discrimination.
