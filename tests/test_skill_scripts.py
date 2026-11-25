"""Unit tests for standalone bundled scripts inside skills/*/scripts/."""

from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fc_mod = _load_module(
    "figcraft_fc",
    REPO_ROOT / "skills" / "figcraft-flatpak" / "scripts" / "_fc.py",
)


class TestFigcraftWrapper(unittest.TestCase):
    def test_parse_script_text_array_jsonl_and_errors(self) -> None:
        is_arr, steps = fc_mod.parse_script_text('[{"command": "frame.create"}]')
        self.assertTrue(is_arr)
        self.assertEqual(steps, [{"command": "frame.create"}])

        is_arr2, steps2 = fc_mod.parse_script_text(
            '{"command": "frame.create"}\n\n{"command": "file.export"}\n'
        )
        self.assertFalse(is_arr2)
        self.assertEqual(len(steps2), 2)

        with self.assertRaises(ValueError):
            fc_mod.parse_script_text("   \n")
        with self.assertRaises(ValueError):
            fc_mod.parse_script_text('{"command": "frame.create"}\n123\n')

    def test_collect_and_rewrite_step_paths(self) -> None:
        mounts: list[str] = []
        step = {
            "command": "command.batch",
            "params": {
                "commands": [
                    {"command": "file.export", "params": {"path": "out/preview.png"}},
                    {"command": "file.open", "params": {"path": "design.fig", "variables": "tokens.json"}},
                    {"command": "file.open", "params": {"path": "https://example.com/a.fig", "variables": '{"a":1}'}},
                ]
            },
        }
        fc_mod.collect_and_rewrite_step_paths(step, mounts)
        cmds = step["params"]["commands"]
        self.assertTrue(Path(cmds[0]["params"]["path"]).is_absolute())
        self.assertTrue(Path(cmds[1]["params"]["variables"]).is_absolute())
        self.assertEqual(cmds[2]["params"]["path"], "https://example.com/a.fig")
        self.assertEqual(cmds[2]["params"]["variables"], '{"a":1}')
        self.assertEqual(len(mounts), 3)

    def test_compact_run_line(self) -> None:
        ok_dict = json.dumps({
            "step": 1,
            "command": "file.export",
            "ok": True,
            "result": {"path": "a.png", "bytes": 1234, "ignored": "huge"},
        })
        parsed_ok = json.loads(fc_mod.compact_run_line(ok_dict))
        self.assertEqual(parsed_ok, {"step": 1, "command": "file.export", "ok": True, "path": "a.png", "bytes": 1234})

        ok_list = json.dumps({
            "step": 2,
            "command": "command.batch",
            "ok": True,
            "result": [{"id": 9, "extra": 1}],
        })
        parsed_list = json.loads(fc_mod.compact_run_line(ok_list))
        self.assertEqual(parsed_list["result"], [{"id": 9}])

        err_line = json.dumps({"step": 3, "command": "node.set", "ok": False, "error": "bad", "rolledBack": True})
        parsed_err = json.loads(fc_mod.compact_run_line(err_line))
        self.assertEqual(parsed_err, {"step": 3, "command": "node.set", "ok": False, "error": "bad", "rolledBack": True})

        self.assertEqual(fc_mod.compact_run_line("not json"), "not json")

    def test_edge_case_limit_and_empty_inspect_code(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertEqual(
                fc_mod.cmd_lookup("ai.storyteller.figcraft", [], ["--limit", "abc", "frame"]),
                2,
            )

            with tempfile.NamedTemporaryFile(suffix=".figcraft") as tf:
                fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
                with patch.object(fc_mod.subprocess, "run", return_value=fake_proc):
                    rc = fc_mod.cmd_inspect_code(
                        "ai.storyteller.figcraft", True, [], [tf.name, "--node", "42"]
                    )
                self.assertEqual(rc, 1)

    def test_standalone_fc_help(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "figcraft-flatpak"
            shutil.copytree(REPO_ROOT / "skills" / "figcraft-flatpak", copied)
            proc = subprocess.run(
                ["bash", str(copied / "scripts" / "fc.sh"), "--help"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertIn("Flatpak-aware wrapper", proc.stdout)


class TestEvalSummary(unittest.TestCase):
    def test_standalone_eval_summary_and_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            copied = tmp_path / "skill-forge"
            shutil.copytree(REPO_ROOT / "skills" / "skill-forge", copied)

            iter_dir = tmp_path / "workspace" / "iteration-1"
            eval_dir = iter_dir / "eval-01-sample"
            for cfg, passed, dur_ms, toks in (
                ("with_skill", True, 1200, 1500),
                ("without_skill", False, 2400, 3200),
            ):
                cfg_dir = eval_dir / cfg
                cfg_dir.mkdir(parents=True)
                (cfg_dir / "grading.json").write_text(
                    json.dumps({
                        "expectations": [
                            {"text": "Produces valid output", "passed": passed, "evidence": "checked"}
                        ]
                    }),
                    encoding="utf-8",
                )
                (cfg_dir / "timing.json").write_text(
                    json.dumps({"duration_ms": dur_ms, "total_tokens": toks}),
                    encoding="utf-8",
                )
            (eval_dir / "eval_metadata.json").write_text(
                json.dumps({"eval_name": "Sample eval"}), encoding="utf-8"
            )

            html_out = iter_dir / "report.html"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(copied / "scripts" / "eval-summary.py"),
                    str(iter_dir),
                    "--skill-name",
                    "demo-skill",
                    "--html",
                    str(html_out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            bench = json.loads((iter_dir / "benchmark.json").read_text(encoding="utf-8"))
            self.assertIn("delta", bench["run_summary"])
            self.assertEqual(bench["run_summary"]["delta"]["pass_rate"], 1.0)
            self.assertTrue((iter_dir / "benchmark.md").is_file())

            html_text = html_out.read_text(encoding="utf-8")
            self.assertIn("demo-skill", html_text)
            self.assertIn("copyFeedback", html_text)
            self.assertIn("delta-banner", html_text)
            self.assertIn("without_skill", html_text)
            self.assertIn("+100.0%", html_text)
            for placeholder in (
                "__TITLE__",
                "__ITERATION__",
                "__SUMMARY_ROWS__",
                "__DELTA_BANNER__",
                "__EVAL_CARDS__",
                "__SKILL_NAME_JSON__",
                "__ITERATION_JSON__",
            ):
                self.assertNotIn(placeholder, html_text)


class TestScanHotspots(unittest.TestCase):
    def test_standalone_scan_hotspots_python_and_ts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            copied = tmp_path / "bottleneck-audit"
            shutil.copytree(REPO_ROOT / "skills" / "bottleneck-audit", copied)

            target = tmp_path / "sample_repo"
            target.mkdir()
            (target / "app.py").write_text(
                (
                    "import time\n\n"
                    "# time.sleep(1) in comment\n\n"
                    "async def bad_handler():\n"
                    '    """time.sleep(1) in docstring"""\n'
                    "    time.sleep(1)\n\n"
                    "def query_users(cursor, users):\n"
                    "    top = [sorted(u) for u in users]\n"
                    "    for u in users:\n"
                    '        cursor.execute("SELECT id FROM t WHERE id = %s", (u,))\n'
                    "        for item in u:\n"
                    "            val = sorted(item)\n"
                    "    return top, val\n"
                ),
                encoding="utf-8",
            )
            (target / "web.ts").write_text(
                (
                    'import fs from "node:fs";\n\n'
                    "/*\n"
                    "for (const f of files) {\n"
                    "  fs.readFileSync(f);\n"
                    "}\n"
                    "*/\n\n"
                    "export async function fetchAll(urls: string[]) {\n"
                    "  for (const u of urls) {\n"
                    "    await fetch(u);\n"
                    "  }\n"
                    "  await Promise.all(urls.map(async (u) => {\n"
                    "    await fetch(u);\n"
                    "  }));\n"
                    "  return urls.reduce((acc, x) => ({ ...acc, [x]: true }), {});\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(copied / "scripts" / "scan-hotspots.py"),
                    "--json",
                    str(target),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            report = json.loads(proc.stdout)
            suspects = report["suspects"]
            by_file_line = {(s["file"], s["line"]): s["rule"] for s in suspects}
            rules_found = {s["rule"] for s in suspects}

            self.assertIn("io-blocking-in-async-py", rules_found)
            self.assertIn("db-n-plus-one", rules_found)
            self.assertIn("cpu-nested-loop", rules_found)
            self.assertIn("cpu-linear-lookup-in-loop", rules_found)
            self.assertIn("io-sequential-await", rules_found)
            self.assertIn("concurrency-unbounded-promise-all", rules_found)
            self.assertIn("memory-reduce-spread", rules_found)

            # Comments, docstrings, top-level sorted comprehension, and parallel Promise.all.map body must not false-trigger
            self.assertNotIn(("app.py", 3), by_file_line)
            self.assertNotIn(("app.py", 6), by_file_line)
            self.assertNotIn(("app.py", 10), by_file_line)
            self.assertNotIn(("web.ts", 5), by_file_line)
            self.assertNotIn(("web.ts", 14), by_file_line)
            self.assertNotIn("io-sync-in-js", rules_found)


class TestBenchCmd(unittest.TestCase):
    def test_bench_save_and_compare(self) -> None:
        bench_py = REPO_ROOT / "skills" / "bottleneck-audit" / "scripts" / "bench-cmd.py"
        with tempfile.TemporaryDirectory() as tmp:
            base_json = Path(tmp) / "base.json"
            p1 = subprocess.run(
                [
                    sys.executable,
                    str(bench_py),
                    "--warmup",
                    "0",
                    "--runs",
                    "2",
                    "--save",
                    str(base_json),
                    "--json",
                    "--",
                    sys.executable,
                    "-c",
                    "pass",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p1.returncode, 0, msg=p1.stderr or p1.stdout)
            res1 = json.loads(p1.stdout)
            self.assertIn("p50", res1["wall_ms"])
            self.assertIn("cpu_ratio", res1)
            self.assertIn("classification", res1)
            self.assertTrue(base_json.is_file())

            p2 = subprocess.run(
                [
                    sys.executable,
                    str(bench_py),
                    "--warmup",
                    "0",
                    "--runs",
                    "2",
                    "--compare",
                    str(base_json),
                    "--json",
                    "--",
                    sys.executable,
                    "-c",
                    "pass",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p2.returncode, 0, msg=p2.stderr or p2.stdout)
            res2 = json.loads(p2.stdout)
            self.assertIn("speedup", res2["comparison"]["p50_ms"])


if __name__ == "__main__":
    unittest.main()
