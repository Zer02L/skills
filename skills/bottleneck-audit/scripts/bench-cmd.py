#!/usr/bin/env python3
"""Deterministic warmup + N-run latency, CPU-ratio, and RSS benchmark (stdlib only)."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _run_once(
    cmd: list[str] | str,
    *,
    use_shell: bool,
    cwd: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    timed_out = False
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        shell=use_shell,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        try:
            proc.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout_s, _on_timeout)
    timer.start()
    user_ms = 0.0
    sys_ms = 0.0
    maxrss_kb = 0.0
    try:
        if hasattr(os, "wait4"):
            _, status, rusage = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
            user_ms = rusage.ru_utime * 1000.0
            sys_ms = rusage.ru_stime * 1000.0
            raw_rss = float(rusage.ru_maxrss)
            maxrss_kb = raw_rss / 1024.0 if sys.platform == "darwin" else raw_rss
        else:
            proc.wait()
    finally:
        timer.cancel()

    wall_ms = (time.perf_counter() - t0) * 1000.0
    if timed_out:
        raise TimeoutError(f"Command timed out after {timeout_s}s")

    return {
        "rc": proc.returncode if proc.returncode is not None else -1,
        "wall_ms": round(wall_ms, 3),
        "user_ms": round(user_ms, 3),
        "sys_ms": round(sys_ms, 3),
        "maxrss_kb": round(maxrss_kb, 1),
    }


def classify_profile(cpu_ratio: float, sys_share: float, cpu_ms: float) -> str:
    if cpu_ratio >= 1.25:
        label = "cpu-bound (multi-core)"
    elif cpu_ratio >= 0.75:
        label = "cpu-bound"
    elif cpu_ratio <= 0.30:
        label = "io-or-wait-bound"
    else:
        label = "mixed (cpu + wait)"
    if cpu_ms > 0 and sys_share >= 0.40:
        label += " (high syscall/kernel overhead)"
    return label


def summarize_samples(
    label: str,
    warmup: int,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    walls = sorted(s["wall_ms"] for s in samples)
    users = [s["user_ms"] for s in samples]
    syss = [s["sys_ms"] for s in samples]
    rss_kbs = [s["maxrss_kb"] for s in samples]

    p50_wall = statistics.median(walls)
    p95_wall = _percentile(walls, 95.0)
    mean_wall = statistics.mean(walls)
    stddev_wall = statistics.stdev(walls) if len(walls) > 1 else 0.0
    med_user = statistics.median(users)
    med_sys = statistics.median(syss)
    med_cpu = med_user + med_sys
    cpu_ratio = (med_cpu / p50_wall) if p50_wall > 0 else 0.0
    sys_share = (med_sys / med_cpu) if med_cpu > 0 else 0.0
    peak_rss_mb = max(rss_kbs) / 1024.0 if rss_kbs else 0.0

    return {
        "command": label,
        "warmup": warmup,
        "runs": len(samples),
        "wall_ms": {
            "min": round(walls[0], 3),
            "p50": round(p50_wall, 3),
            "p95": round(p95_wall, 3),
            "mean": round(mean_wall, 3),
            "max": round(walls[-1], 3),
            "stddev": round(stddev_wall, 3),
        },
        "user_ms": round(med_user, 3),
        "sys_ms": round(med_sys, 3),
        "cpu_ratio": round(cpu_ratio, 3),
        "sys_share": round(sys_share, 3),
        "maxrss_mb": round(peak_rss_mb, 2),
        "classification": classify_profile(cpu_ratio, sys_share, med_cpu),
        "samples": samples,
    }


def build_comparison(base: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    def _delta(b: float, c: float) -> dict[str, Any]:
        pct = ((c - b) / b * 100.0) if b > 0 else 0.0
        speedup = (b / c) if c > 0 else 0.0
        return {
            "baseline": b,
            "current": c,
            "delta_pct": round(pct, 2),
            "speedup": round(speedup, 3),
        }

    return {
        "baseline_command": base.get("command", ""),
        "p50_ms": _delta(base["wall_ms"]["p50"], cur["wall_ms"]["p50"]),
        "p95_ms": _delta(base["wall_ms"]["p95"], cur["wall_ms"]["p95"]),
        "mean_ms": _delta(base["wall_ms"]["mean"], cur["wall_ms"]["mean"]),
        "maxrss_mb": _delta(base["maxrss_mb"], cur["maxrss_mb"]),
    }


def _fmt_speedup(speedup: float) -> str:
    if speedup >= 1.0:
        return f"{speedup:.2f}x faster"
    if speedup > 0:
        return f"{(1.0 / speedup):.2f}x slower"
    return "n/a"


def print_report(result: dict[str, Any]) -> None:
    w = result["wall_ms"]
    print(f"Benchmark: `{result['command']}` (warmup={result['warmup']}, runs={result['runs']})")
    print(
        f"- **Classification:** {result['classification']} "
        f"(cpu_ratio={result['cpu_ratio']:.2f}, sys_share={result['sys_share']:.0%})"
    )
    print(
        f"- **Wall (ms):** min={w['min']:.2f} | p50={w['p50']:.2f} | p95={w['p95']:.2f} | "
        f"mean={w['mean']:.2f} ± {w['stddev']:.2f} | max={w['max']:.2f}"
    )
    print(
        f"- **Resources (median):** user={result['user_ms']:.2f} ms | "
        f"sys={result['sys_ms']:.2f} ms | peak_rss={result['maxrss_mb']:.2f} MB"
    )

    comp = result.get("comparison")
    if comp:
        print("\n| Metric | Baseline | Current | Delta | Speedup |")
        print("| --- | ---: | ---: | ---: | --- |")
        for key, title in (
            ("p50_ms", "p50 wall (ms)"),
            ("p95_ms", "p95 wall (ms)"),
            ("mean_ms", "mean wall (ms)"),
            ("maxrss_mb", "peak RSS (MB)"),
        ):
            d = comp[key]
            note = "-" if key == "maxrss_mb" else _fmt_speedup(d["speedup"])
            print(
                f"| {title} | {d['baseline']:.2f} | {d['current']:.2f} "
                f"| {d['delta_pct']:+.1f}% | {note} |"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure command latency (p50/p95), CPU ratio, peak RSS, and before/after delta."
    )
    parser.add_argument("--warmup", type=int, default=1, help="Warmup runs (default: 1).")
    parser.add_argument("--runs", type=int, default=5, help="Measured runs (default: 5).")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-run timeout seconds (default: 60).")
    parser.add_argument("--cwd", help="Working directory for the command.")
    parser.add_argument("--shell", dest="shell_cmd", help="Shell command string to run via /bin/sh.")
    parser.add_argument("--allow-nonzero", action="store_true", help="Do not fail on non-zero exit code.")
    parser.add_argument("--save", help="Save JSON benchmark result to file.")
    parser.add_argument("--compare", help="Compare against a baseline JSON saved via --save.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run (after --).")
    args = parser.parse_args()

    cmd_list = list(args.cmd)
    if cmd_list and cmd_list[0] == "--":
        cmd_list = cmd_list[1:]

    if args.shell_cmd and cmd_list:
        print("Error: use either --shell or positional command, not both.", file=sys.stderr)
        return 2
    if not args.shell_cmd and not cmd_list:
        print("Error: provide a command after '--' or via --shell.", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("Error: --runs must be >= 1.", file=sys.stderr)
        return 2
    if args.warmup < 0:
        print("Error: --warmup must be >= 0.", file=sys.stderr)
        return 2

    target_cmd: list[str] | str = args.shell_cmd if args.shell_cmd else cmd_list
    label = args.shell_cmd if args.shell_cmd else " ".join(cmd_list)
    use_shell = bool(args.shell_cmd)

    try:
        for i in range(args.warmup):
            res = _run_once(target_cmd, use_shell=use_shell, cwd=args.cwd, timeout_s=args.timeout)
            if res["rc"] != 0 and not args.allow_nonzero:
                print(f"Error: warmup run {i + 1} exited with code {res['rc']}.", file=sys.stderr)
                return 1

        samples: list[dict[str, Any]] = []
        for i in range(args.runs):
            res = _run_once(target_cmd, use_shell=use_shell, cwd=args.cwd, timeout_s=args.timeout)
            if res["rc"] != 0 and not args.allow_nonzero:
                print(f"Error: measured run {i + 1} exited with code {res['rc']}.", file=sys.stderr)
                return 1
            samples.append(res)
    except (TimeoutError, OSError) as exc:
        print(f"Error running benchmark: {exc}", file=sys.stderr)
        return 1

    result = summarize_samples(label, args.warmup, samples)

    if args.compare:
        base_path = Path(args.compare).expanduser().resolve()
        if not base_path.is_file():
            print(f"Error: baseline file not found: {base_path}", file=sys.stderr)
            return 1
        base_data = json.loads(base_path.read_text(encoding="utf-8"))
        result["comparison"] = build_comparison(base_data, result)

    if args.save:
        save_path = Path(args.save).expanduser().resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
