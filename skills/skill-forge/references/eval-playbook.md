# Cross-Agent A/B Evaluation Playbook

Use this playbook when verifying behavioral quality, writing-style skills, or before/after revisions without relying on `claude -p`.

## 1. Workspace layout (schema-compatible with `skill-creator`)

Store eval artifacts in `<skill-name>-workspace/` as a sibling directory of the skill (ignored by Git via `*-workspace/`):

```text
<skill-name>-workspace/
└── iteration-1/
    ├── eval-01-descriptive-name/
    │   ├── eval_metadata.json
    │   ├── with_skill/
    │   │   ├── outputs/
    │   │   ├── grading.json
    │   │   └── timing.json
    │   └── without_skill/       # or old_skill/ when iterating on an existing skill
    │       ├── outputs/
    │       ├── grading.json
    │       └── timing.json
    ├── benchmark.json
    ├── benchmark.md
    └── report.html
```

## 2. Running parallel `with_skill` vs baseline tasks

1. Pick 2–4 realistic user prompts (matching real phrasing, file paths, and edge cases).
2. Spawn two subagents per prompt in the same turn using your active harness (`invoke_subagent` / `delegate_task` in Antigravity, Codex subagents, or sequential runs if subagents are unavailable):
   - **With skill:** tell the worker to read `<skill-dir>/SKILL.md` first and follow its workflow; save deliverables to `.../with_skill/outputs/`.
   - **Baseline:** either no skill (`without_skill/outputs/`) for a new skill, or a snapshot copy (`old_skill/outputs/`) when improving an existing skill.
3. Capture wall-clock timing (and `total_tokens` when reported by your harness) into `timing.json`:
   ```json
   {"duration_ms": 12450, "total_tokens": 18200}
   ```

## 3. Objective grading & optional blind comparison

Draft verifiable assertions (not vague praise) and evaluate each run into `grading.json`:

```json
{
  "expectations": [
    {"text": "Produces valid output file without syntax errors", "passed": true, "evidence": "validate.py exited 0"},
    {"text": "Avoids dumping unfiltered command list", "passed": true, "evidence": "Used fc.sh lookup --limit 5"}
  ]
}
```

For subjective quality (design taste, prose clarity), optionally launch a blind comparator subagent: shuffle `with_skill` vs baseline outputs as **Response A** and **Response B** without revealing labels, and record which produced cleaner structure, fewer wasted steps, and better adherence to user constraints.

## 4. Aggregating results & static HTML review

Run `scripts/eval-summary.py` from the skill directory:

```bash
scripts/eval-summary.py <workspace>/iteration-1 \
  --skill-name "<skill-name>" \
  --html <workspace>/iteration-1/report.html
```

This writes `benchmark.json`, `benchmark.md`, and a self-contained static `report.html` (no background HTTP server needed). Open `report.html` on Linux via `xdg-open` or inspect `benchmark.md` directly, then revise the skill based on failed assertions and observed transcript friction.
