---
name: __SKILL_NAME__
description: >-
  TODO: Describe what this skill does and explicitly list the situations,
  phrases, and tasks that should trigger it.
---

# __SKILL_NAME__

## When to use

- Describe the tasks, triggers, and contexts where an agent should load this skill.
- Clarify boundaries or cases where this skill should NOT be used.

## Workflow

1. Step 1: ...
2. Step 2: ...
3. Step 3: ...

## Rules

- Keep instructions concrete, imperative, and focused on non-obvious constraints.
- Keep `SKILL.md` concise (target <= 150 lines / <= 1 500 tokens; hard warning at 500 lines) and move bulky details into `references/`.

## Resources

Optional bundled directories inside this skill folder:

- `scripts/` — deterministic helper scripts the agent can execute.
- `references/` — detailed docs loaded into context only when needed.
- `assets/` — templates, icons, or output files copied into deliverables.
