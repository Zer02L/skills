#!/usr/bin/env python3
"""Aggregate cross-agent A/B grading/timing results into benchmark.json, benchmark.md, and static HTML."""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _mean_std(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"mean": 0.0, "stddev": 0.0}
    mean = sum(vals) / len(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return {"mean": round(mean, 4), "stddev": round(std, 4)}


def load_iteration(iter_dir: Path) -> dict[str, list[dict[str, Any]]]:
    runs_by_cfg: dict[str, list[dict[str, Any]]] = {}
    for eval_dir in sorted(p for p in iter_dir.iterdir() if p.is_dir() and p.name.startswith("eval-")):
        meta_file = eval_dir / "eval_metadata.json"
        eval_name = eval_dir.name
        if meta_file.is_file():
            try:
                eval_name = json.loads(meta_file.read_text(encoding="utf-8")).get("eval_name") or eval_dir.name
            except Exception:
                pass
        for cfg_dir in sorted(p for p in eval_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            grading_file = cfg_dir / "grading.json"
            if not grading_file.is_file():
                continue
            grading = json.loads(grading_file.read_text(encoding="utf-8"))
            exps = grading.get("expectations") or []
            passed_cnt = sum(1 for e in exps if e.get("passed") is True)
            total_cnt = len(exps)
            pass_rate = (passed_cnt / total_cnt) if total_cnt else 0.0

            timing_file = cfg_dir / "timing.json"
            duration_s = None
            tokens = None
            if timing_file.is_file():
                tdata = json.loads(timing_file.read_text(encoding="utf-8"))
                if "duration_ms" in tdata and isinstance(tdata["duration_ms"], (int, float)):
                    duration_s = tdata["duration_ms"] / 1000.0
                elif "total_duration_seconds" in tdata and isinstance(tdata["total_duration_seconds"], (int, float)):
                    duration_s = float(tdata["total_duration_seconds"])
                if "total_tokens" in tdata and isinstance(tdata["total_tokens"], (int, float)):
                    tokens = float(tdata["total_tokens"])

            runs_by_cfg.setdefault(cfg_dir.name, []).append({
                "eval_dir": eval_dir.name,
                "eval_name": eval_name,
                "pass_rate": pass_rate,
                "passed": passed_cnt,
                "total": total_cnt,
                "duration_seconds": duration_s,
                "total_tokens": tokens,
                "expectations": exps,
            })
    return runs_by_cfg


def build_benchmark(iter_dir: Path, skill_name: str) -> dict[str, Any]:
    runs_by_cfg = load_iteration(iter_dir)
    if not runs_by_cfg:
        raise ValueError(f"No graded eval-*/<config>/grading.json runs found in {iter_dir}")

    summary: dict[str, Any] = {}
    for cfg, items in runs_by_cfg.items():
        pass_stats = _mean_std([x["pass_rate"] for x in items])
        durs = [x["duration_seconds"] for x in items if x["duration_seconds"] is not None]
        toks = [x["total_tokens"] for x in items if x["total_tokens"] is not None]
        summary[cfg] = {
            "runs": len(items),
            "pass_rate": pass_stats,
            "duration_seconds": _mean_std(durs) if durs else None,
            "total_tokens": _mean_std(toks) if toks else None,
        }

    baseline_cfg = "without_skill" if "without_skill" in summary else ("old_skill" if "old_skill" in summary else None)
    if "with_skill" in summary and baseline_cfg:
        w = summary["with_skill"]
        b = summary[baseline_cfg]
        delta_pr = round(w["pass_rate"]["mean"] - b["pass_rate"]["mean"], 4)
        delta_dur = (
            round(w["duration_seconds"]["mean"] - b["duration_seconds"]["mean"], 2)
            if w["duration_seconds"] and b["duration_seconds"]
            else None
        )
        delta_tok = (
            round(w["total_tokens"]["mean"] - b["total_tokens"]["mean"], 1)
            if w["total_tokens"] and b["total_tokens"]
            else None
        )
        summary["delta"] = {
            "baseline": baseline_cfg,
            "pass_rate": delta_pr,
            "duration_seconds": delta_dur,
            "total_tokens": delta_tok,
        }

    return {
        "skill_name": skill_name,
        "iteration": iter_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_summary": summary,
        "configs": runs_by_cfg,
    }


def render_markdown(bench: dict[str, Any]) -> str:
    lines = [
        f"# Benchmark: {bench['skill_name']} ({bench['iteration']})",
        "",
        "| Config | Runs | Pass Rate | Duration (s) | Tokens |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for cfg, st in bench["run_summary"].items():
        if cfg == "delta":
            continue
        pr = f"{st['pass_rate']['mean']:.1%} ± {st['pass_rate']['stddev']:.1%}"
        dur = f"{st['duration_seconds']['mean']:.2f} ± {st['duration_seconds']['stddev']:.2f}" if st["duration_seconds"] else "n/a"
        tok = f"{st['total_tokens']['mean']:.0f} ± {st['total_tokens']['stddev']:.0f}" if st["total_tokens"] else "n/a"
        lines.append(f"| {cfg} | {st['runs']} | {pr} | {dur} | {tok} |")

    if "delta" in bench["run_summary"]:
        d = bench["run_summary"]["delta"]
        lines.extend([
            "",
            f"**Delta (`with_skill` vs `{d['baseline']}`):** "
            f"pass_rate `{d['pass_rate']:+.1%}`"
            + (f", duration `{d['duration_seconds']:+.2f}s`" if d["duration_seconds"] is not None else "")
            + (f", tokens `{d['total_tokens']:+.0f}`" if d["total_tokens"] is not None else ""),
        ])
    return "\n".join(lines) + "\n"


def render_html(bench: dict[str, Any]) -> str:
    summary_rows = []
    for cfg, st in bench["run_summary"].items():
        if cfg == "delta":
            continue
        pr = f"{st['pass_rate']['mean']:.1%} (±{st['pass_rate']['stddev']:.1%})"
        dur = f"{st['duration_seconds']['mean']:.2f}s" if st["duration_seconds"] else "n/a"
        tok = f"{st['total_tokens']['mean']:.0f}" if st["total_tokens"] else "n/a"
        summary_rows.append(
            f"<tr><td><strong>{html.escape(cfg)}</strong></td><td>{st['runs']}</td>"
            f"<td>{pr}</td><td>{dur}</td><td>{tok}</td></tr>"
        )

    eval_cards = []
    for cfg, items in bench["configs"].items():
        for item in items:
            ex_rows = []
            for ex in item["expectations"]:
                mark = "PASS" if ex.get("passed") else "FAIL"
                cls = "pass" if ex.get("passed") else "fail"
                ex_rows.append(
                    f"<li><span class='badge {cls}'>{mark}</span> "
                    f"<strong>{html.escape(str(ex.get('text', '')))}</strong>"
                    f"<div class='ev'>{html.escape(str(ex.get('evidence', '')))}</div></li>"
                )
            eval_cards.append(
                f"<div class='card'><h3>{html.escape(item['eval_name'])} — {html.escape(cfg)} "
                f"({item['passed']}/{item['total']})</h3><ul>{''.join(ex_rows)}</ul></div>"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Eval Report: {html.escape(bench['skill_name'])}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 24px auto; max-width: 960px; padding: 0 16px; color: #111827; background: #f9fafb; }}
  h1 {{ font-size: 20px; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; margin-bottom: 20px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #e5e7eb; font-size: 14px; }}
  .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; }}
  .card h3 {{ margin: 0 0 10px; font-size: 15px; }}
  ul {{ margin: 0; padding-left: 18px; }}
  li {{ margin-bottom: 8px; font-size: 13.5px; }}
  .badge {{ display: inline-block; font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 4px; margin-right: 6px; }}
  .pass {{ background: #dcfce7; color: #166534; }}
  .fail {{ background: #fee2e2; color: #991b1b; }}
  .ev {{ color: #4b5563; font-size: 12.5px; margin-top: 2px; }}
</style>
</head>
<body>
  <h1>Eval Report: {html.escape(bench['skill_name'])} ({html.escape(bench['iteration'])})</h1>
  <table>
    <thead><tr><th>Config</th><th>Runs</th><th>Pass Rate</th><th>Duration</th><th>Tokens</th></tr></thead>
    <tbody>{''.join(summary_rows)}</tbody>
  </table>
  {''.join(eval_cards)}
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate A/B skill eval results into benchmark.json, benchmark.md, and optional HTML."
    )
    parser.add_argument("iteration_dir", help="Path to iteration directory (containing eval-*/ subfolders).")
    parser.add_argument("--skill-name", default="skill", help="Skill name for headers.")
    parser.add_argument("--html", help="Optional output path for static HTML report.")
    args = parser.parse_args()

    iter_dir = Path(args.iteration_dir).expanduser().resolve()
    if not iter_dir.is_dir():
        print(f"Error: iteration directory not found: {iter_dir}", file=sys.stderr)
        return 1

    bench = build_benchmark(iter_dir, args.skill_name)
    (iter_dir / "benchmark.json").write_text(json.dumps(bench, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = render_markdown(bench)
    (iter_dir / "benchmark.md").write_text(md, encoding="utf-8")
    if args.html:
        Path(args.html).expanduser().resolve().write_text(render_html(bench), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
