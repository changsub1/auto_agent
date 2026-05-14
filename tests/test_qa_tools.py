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
        log_text = (self.workspace / "evidence" / "command_log.jsonl").read_text(encoding="utf-8")
        self.assertIn('"tool": "file_probe"', log_text)

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


if __name__ == "__main__":
    unittest.main()
