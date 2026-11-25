# AGENTS.md

Instructions for AI coding agents working in `/home/zerg/Projects/skills`.

## Repository layout

- `skills/<skill-name>/SKILL.md` — custom skills authored in this repo (one folder per skill, kebab-case matching `name:` in YAML frontmatter).
- `skills/<skill-name>/scripts|references|assets|evals/` — optional bundled resources for progressive disclosure and trigger/A-B evals.
- `templates/skill-template/` — starter template (`SKILL.md`, `hook-triggers.json`, `evals/trigger-tests.json`; kept outside `skills/` so skill scanners skip it).
- `scripts/check.py` — unified repository quality gate (`py_compile`, `validate.py --strict`, `audit-skill.py --strict`, `test-triggers.py`, `unittest`).
- `scripts/new-skill.sh` — scaffold a new skill under `skills/<skill-name>/` (`scripts/lib/scaffold.py`; pass `--with-hook` for starter `hook-triggers.json` + `evals/trigger-tests.json`).
- `scripts/validate.py` — validate frontmatter, naming, structure, optional `hook-triggers.json`, and size rules via `skills/skill-forge/scripts/_spec.py` (pure Python 3 stdlib; PyYAML is optional).
- `scripts/sync-to-manager.sh` — validate and install/update skills into Skills Manager (`scripts/lib/manager.py`), optionally deploying to agents (`--deploy`), syncing hooks (`--hooks`), and pushing Git Backup (`--backup`).
- `scripts/skill-hook-router.py` — universal prompt/shell hook router reading `skills/*/hook-triggers.json`.
- `scripts/sync-hooks.py` — idempotent installer for `antigravity`, `codex`, `claude_code`, `gemini_cli`, and `opencode` (`--status`, `--dry-run`, `--uninstall`), using `scripts/lib/opencode-plugin.js.tpl`.
- `scripts/lib/` — shared helpers exclusively for repo-level tooling (`scripts/`).
- `tests/` — pure stdlib `unittest` suite covering spec validation, hook parity, hook installer, repo tooling, and bundled skill scripts.
- `.github/workflows/ci.yml` — CI workflow running `python3 scripts/check.py --require-js`.

## Authoring conventions & standalone portability

- **Standalone portability:** Each `skills/<skill-name>/` folder MUST remain 100% self-contained (zero imports from repo-root `scripts/` or `scripts/lib/`), because Skills Manager copies each skill directory independently into `~/.skills-manager/skills/<skill-name>/`. Place internal helper Python modules inside `skills/<skill-name>/scripts/_*.py` (automatically excluded from CLI script count / executable checks).
- Directory name under `skills/` must be `kebab-case` (`^[a-z0-9]+(-[a-z0-9]+)*$`, max 64 chars) and match `name:` in `SKILL.md` frontmatter.
- Allowed top-level YAML frontmatter keys: `name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`.
- Make `description` specific and trigger-rich (max 1024 chars, no `<` or `>` characters, no leftover `TODO:`). Include both what the skill does and the exact situations/phrases that should trigger it.
- Keep `SKILL.md` concise (target `<= 150` lines / `<= 1 500` tokens; hard warning at 500 lines). Move lengthy references, deterministic scripts, and output templates into `references/`, `scripts/`, and `assets/`.
- Never leave a nested `.git` directory inside a skill folder.

## Source-of-truth & Skills Manager integration

- **Single source of truth:** Always edit custom skills here in `/home/zerg/Projects/skills/skills/<skill-name>/`, **never** directly inside `~/.skills-manager/skills/<skill-name>/` (a future `skills update` will overwrite direct library edits).
- Run the full quality gate before syncing or committing:
  ```bash
  ./scripts/check.py --require-js
  # Or run only structure/hook validation:
  ./scripts/validate.py --strict
  ```
- Sync to Skills Manager (preview first with `--dry-run` if unsure):
  ```bash
  ./scripts/sync-to-manager.sh <skill-name> --deploy claude_code
  ```
- Note: the user's Skills Manager library also contains `skill-creator` (for designing/evaluating skills) and `manage-skills` (CLI guide for `skills-manager-cli`).

## Switching a skill to a GitHub remote later

Once changes are pushed to GitHub, you can switch a local-backed skill to track the GitHub repo in place (keeping its id, tags, presets, and deployments):

```bash
~/.skills-manager/bin/skills-manager-cli skills set-source <skill-name> \
  --git-url https://github.com/Zer02L/skills/tree/main/skills/<skill-name>
```
