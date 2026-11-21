---
name: skill-forge
description: Design, build, audit, optimize, and benchmark agent skills (SKILL.md, scripts/, references/, hook-triggers.json) for Antigravity, Codex, Claude Code, Gemini CLI, OpenCode, and Skills Manager. Use whenever creating a new skill, refactoring or slimming a bloated skill, auditing token budgets, wrapping a CLI/Flatpak/Docker tool in a skill, testing prompt/shell triggers, or running A/B evals. Do NOT use merely to list, install, deploy, or remove existing skills (use manage-skills).
compatibility: Python 3 stdlib (optional bun or node for JS regex parity checks)
---

# Skill Forge

Create lean, measurable, cross-agent skills. Keep `SKILL.md` small, push deterministic work into `scripts/`, verify tools against live behavior before writing rules, and measure token and latency gains instead of guessing.

## 1. Six-stage workflow

1. **Intake:** Clarify the exact job, target runtime/sandbox (host CLI, Flatpak, Docker, API, or pure methodology), phrases that should trigger the skill, near-misses that should NOT trigger it, and whether A/B evals are needed.
2. **Probe (mandatory for CLI/tool skills):** Inspect the live binary before authoring rules — run `--help`, inspect sandbox mounts/permissions, check JSON schemas and unfiltered command-dump sizes, and measure baseline latency. Capture real syntax pitfalls so the skill prevents trial-and-error loops on day one.
3. **Architect:** Split responsibilities deliberately across layers:
   - `SKILL.md` — concise workflow, exact non-obvious constraints, and minimal working example.
   - `scripts/` — wrap multi-step boilerplate, auto-mount sandbox paths, batch calls, compact verbose JSON, and bound command lookups (`--limit`).
   - `references/` — move long parameter catalogs, schemas, and optional setup guides out of `SKILL.md`.
   - `hook-triggers.json` — add only when deterministic prompt routing or shell guardrails (`deny_shell`) prevent costly mistakes.
4. **Author:** If working inside a skills repository, scaffold with its `scripts/new-skill.sh <name> [--with-scripts] [--with-references] [--with-hook]`. Explain *why* a rule exists instead of shouting `ALWAYS`/`NEVER`, generalize beyond individual test cases, and never hardcode local user/repo paths inside the skill folder.
5. **Test & Measure:**
   - Run `scripts/audit-skill.py --strict <skill-dir>` to verify structure and token budget.
   - If `hook-triggers.json` + `evals/trigger-tests.json` exist, run `scripts/test-triggers.py <skill-dir> --live-router --js-check` to verify 100% pass across Python, JS, and hook adapters.
   - Exercise every bundled script on real inputs and record actual before/after metrics (bytes/tokens, tool turns, runtime ms). For qualitative or behavioral skills, run cross-agent A/B evals using `references/eval-playbook.md` and `scripts/eval-summary.py`.
6. **Ship & Hook:** In a skills repository, run `./scripts/validate.py --strict <name>`, preview with `./scripts/sync-to-manager.sh --dry-run <name> [--deploy <agent>] [--hooks]`, then sync and commit.

## 2. Hard token & quality budgets

| Layer | Target budget | Why |
| --- | --- | --- |
| Frontmatter (idle) | <= 150 tokens | Loaded in every session; keep `description` trigger-rich and <= 1024 chars without `<` or `>` |
| `SKILL.md` (active) | <= 1 500 tokens (<= 150 lines) | Keeps room for user code and tool outputs |
| `references/*.md` | <= 2 500 tokens each | Loaded only when a specific subtask needs deep details |
| `scripts/*` | Stdlib only, executable | Executed via shell (`0` prompt tokens until read); keep outputs compact |

## 3. Bundled tools (relative to this skill directory)

| Script | Purpose |
| --- | --- |
| `scripts/audit-skill.py [--strict] [--json] <skill-dir>...` | Validate structure + `hook-triggers.json` JS portability and measure idle/active token budgets |
| `scripts/test-triggers.py [--live-router] [--js-check] <skill-dir>` | Test `evals/trigger-tests.json` (`should_trigger` / `should_not_trigger` / `deny_shell`) across Python, JS, and live router |
| `scripts/eval-summary.py <iteration-dir> [--skill-name N] [--html OUT.html]` | Aggregate A/B `grading.json` + `timing.json` into `benchmark.json`, `benchmark.md`, and static HTML review report |

## 4. Progressive disclosure references

- Read `references/authoring-guide.md` for writing style, CLI/MCP token-optimization levers, and Python+JS `hook-triggers.json` regex rules (including why Cyrillic must never use `\b`).
- Read `references/eval-playbook.md` when running cross-agent A/B tests, blind comparisons, or HTML benchmark reviews without `claude -p`.
