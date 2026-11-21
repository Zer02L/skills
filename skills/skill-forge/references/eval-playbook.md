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

## 3. Objective grading vs subjective quality

Never force artificial assertions onto subjective outcomes. Split verification by domain:

- **Objective tasks (CLI, build, code transforms):** Check programmatically via scripts (`test_output.py`, `validate.py`). An assertion passes only when there is genuine substance, not superficial compliance (e.g. file exists AND has valid data).
- **Subjective tasks (design taste, writing style, UX):** Evaluate qualitatively via human review or a Blind Comparator subagent.

Evaluate each run into `grading.json`:

```json
{
  "expectations": [
    {"text": "Produces valid output file without syntax errors", "passed": true, "evidence": "validate.py exited 0"},
    {"text": "Avoids dumping unfiltered command list", "passed": true, "evidence": "Used fc.sh lookup --limit 5"}
  ]
}
```

## 4. Evaluator subagent prompt templates

When automating grading or A/B reviews, spawn subagents with these lean prompt templates:

### Grader prompt template
```markdown
Evaluate expectations against execution transcript and output files:
- Expectations: <list of assertions>
- Outputs dir: <path/to/outputs>
- Transcript: <path/to/transcript.jsonl or log.md>

Rules:
1. PASS only when evidence demonstrates genuine task completion, not superficial compliance (e.g. right filename but empty content is a FAIL).
2. Critique the evals: if an assertion passed trivially without doing the real work, or an important outcome is unverified, flag it under "critique".
Save result to sibling grading.json: {"expectations": [{"text": "...", "passed": true|false, "evidence": "..."}], "eval_critique": []}
```

### Blind comparator prompt template (Subjective A/B)
```markdown
Compare two outputs without knowing which skill produced them.
- Output A: <path/to/out_a>
- Output B: <path/to/out_b>
- Original Task: <prompt>

Score both on 1-5 scale across two dimensions:
- Content: Correctness, Completeness, Accuracy
- Structure: Organization, Formatting, Usability
Determine the winner (A or B) and save comparison.json:
{"winner": "A"|"B", "reasoning": "...", "scores": {"A": {"content": N, "structure": N}, "B": {"content": N, "structure": N}}}
```

### Post-hoc analyzer prompt template
```markdown
Unblind comparison results to extract actionable skill improvements:
- Winner: <"A" or "B">
- Winner skill: <path> | Loser skill: <path>
- Winner transcript: <path> | Loser transcript: <path>

Analyze:
1. Exactly where did the loser transcript diverge (unnecessary steps, missing tool/script, vague instruction)?
2. Repeated work: did either side write ad-hoc helper scripts that should be bundled into scripts/?
Save findings to analysis.json with prioritized suggestions for the loser skill.
```

## 5. Aggregating results & static HTML review

Run `scripts/eval-summary.py` from the skill directory:

```bash
scripts/eval-summary.py <workspace>/iteration-1 \
  --skill-name "<skill-name>" \
  --html <workspace>/iteration-1/report.html
```

This writes `benchmark.json`, `benchmark.md`, and an interactive standalone `report.html` (no HTTP server needed):
- Inspect pass rates, duration, and token deltas across configurations.
- Enter notes or per-card comments directly in the browser.
- Click **"Copy Feedback for Agent"** to copy a Markdown summary straight to your clipboard for pasting into chat, or **"Download feedback.json"** for local file workflows.
