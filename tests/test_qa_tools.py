from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QAToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        shutil.copytree(PROJECT_ROOT / "qa_tools", self.workspace / "qa_tools")
        (self.workspace / "app").mkdir()
        (self.workspace / "app" / "README.md").write_text("Usage: run self-test.\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_file_probe_records_evidence_and_command_log(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.workspace / "qa_tools" / "file_probe.py"),
                "--name",
                "readme",
                "--path",
                "app/README.md",
                "--contains",
                "self-test",
            ],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads((self.workspace / "evidence" / "files" / "readme_result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["read_policy"], "prefix_preview")
        self.assertFalse(result["large_file"])
        self.assertEqual(result["contains_results"]["self-test"], True)
        log_text = (self.workspace / "evidence" / "command_log.jsonl").read_text(encoding="utf-8")
        self.assertIn('"tool": "file_probe"', log_text)

    def test_file_probe_streams_large_files_without_full_preview(self) -> None:
        large_file = self.workspace / "app" / "large.log"
        large_file.write_text(("A" * 200_000) + "\nTAIL_TOKEN\n", encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable,
                str(self.workspace / "qa_tools" / "file_probe.py"),
                "--name",
                "large-log",
                "--path",
                "app/large.log",
                "--contains",
                "TAIL_TOKEN",
                "--max-preview-chars",
                "80",
                "--max-full-read-bytes",
                "1000",
            ],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads((self.workspace / "evidence" / "files" / "large-log_result.json").read_text(encoding="utf-8"))
        preview = (self.workspace / "evidence" / "files" / "large-log_preview.txt").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["large_file"])
        self.assertEqual(result["contains_results"]["TAIL_TOKEN"], True)
        self.assertTrue(result["preview_truncated"])
        self.assertLessEqual(len(preview), 81)
        self.assertNotIn("TAIL_TOKEN", preview)

    def test_command_probe_runs_without_shell_and_records_outputs(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.workspace / "qa_tools" / "command_probe.py"),
                "--name",
                "python-version",
                "--cwd",
                ".",
                "--",
                sys.executable,
                "--version",
            ],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(
            (self.workspace / "evidence" / "commands" / "python-version_result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue((self.workspace / "evidence" / "commands" / "python-version_stdout.txt").exists())

    def test_command_probe_truncates_large_output_artifacts(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.workspace / "qa_tools" / "command_probe.py"),
                "--name",
                "large-output",
                "--cwd",
                ".",
                "--max-output-chars",
                "80",
                "--",
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 5000)",
            ],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(
            (self.workspace / "evidence" / "commands" / "large-output_result.json").read_text(encoding="utf-8")
        )
        stdout_text = (self.workspace / "evidence" / "commands" / "large-output_stdout.txt").read_text(encoding="utf-8")
        self.assertTrue(result["stdout_truncated"])
        self.assertEqual(result["stdout_chars"], 5000)
        self.assertLess(len(stdout_text), 140)


if __name__ == "__main__":
    unittest.main()
