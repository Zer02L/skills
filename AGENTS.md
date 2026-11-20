# AGENTS.md

Instructions for AI coding agents working in `/home/zerg/Projects/skills`.

## Repository layout

- `skills/<skill-name>/SKILL.md` — custom skills authored in this repo (one folder per skill, kebab-case matching `name:` in YAML frontmatter).
- `skills/<skill-name>/scripts|references|assets/` — optional bundled resources for progressive disclosure.
- `templates/skill-template/SKILL.md` — starter template (kept outside `skills/` so skill scanners skip it).
- `scripts/new-skill.sh` — scaffold a new skill under `skills/<skill-name>/`.
- `scripts/validate.py` — validate frontmatter, naming, structure, and size rules (pure Python 3 stdlib; PyYAML is optional).
- `scripts/sync-to-manager.sh` — validate and install/update skills into Skills Manager (`~/.skills-manager/bin/skills-manager-cli`), optionally deploying to agents and pushing Git Backup.

## Authoring conventions

- Directory name under `skills/` must be `kebab-case` (`^[a-z0-9]+(-[a-z0-9]+)*$`, max 64 chars) and match `name:` in `SKILL.md` frontmatter.
- Allowed top-level YAML frontmatter keys: `name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`.
- Make `description` specific and trigger-rich (max 1024 chars, no `<` or `>` characters, no leftover `TODO:`). Include both what the skill does and the exact situations/phrases that should trigger it.
- Keep `SKILL.md` concise (under 500 lines). Move lengthy references, deterministic scripts, and output templates into `references/`, `scripts/`, and `assets/`.
- Never leave a nested `.git` directory inside a skill folder.

## Source-of-truth & Skills Manager integration

- **Single source of truth:** Always edit custom skills here in `/home/zerg/Projects/skills/skills/<skill-name>/`, **never** directly inside `~/.skills-manager/skills/<skill-name>/` (a future `skills update` will overwrite direct library edits).
- Validate before syncing or committing:
  ```bash
  ./scripts/validate.py --strict
  ```
- Sync to Skills Manager (preview first with `--dry-run` if unsure):
  ```bash
  ./scripts/sync-to-manager.sh <skill-name> --deploy claude_code
  ```
- Note: the user's Skills Manager library also contains `skill-creator` (for designing/evaluating skills) and `manage-skills` (CLI guide for `skills-manager-cli`).

## Switching a skill to a GitHub remote later

Once this repo is pushed to GitHub, switch a local-backed skill to track the GitHub repo in place (keeping its id, tags, presets, and deployments):

```bash
~/.skills-manager/bin/skills-manager-cli skills set-source <skill-name> \
  --git-url https://github.com/<user>/<repo>/tree/main/skills/<skill-name>
```
