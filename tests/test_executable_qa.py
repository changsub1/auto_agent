from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from executable_qa import run_executable_qa


class ManifestExecutableQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app_dir = self.root / "generated_app"
        self.qa_dir = self.root / "qa"
        self.app_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_manifest(self, payload: dict[str, object]) -> None:
        (self.app_dir / "codex_app_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_manifest_check_command_runs_before_framework_detection(self) -> None:
        self.write_manifest(
            {
                "version": 1,
                "app_type": "cli",
                "runtime": "python",
                "checks": [
                    {
                        "name": "manifest check",
                        "command": [sys.executable, "-c", "print('manifest ok')"],
                        "timeout_seconds": 30,
                    }
                ],
            }
        )

        result = run_executable_qa(self.app_dir, self.qa_dir)

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.app_type, "cli")
        stdout_files = list(self.qa_dir.glob("*manifest_check*_stdout.txt"))
        self.assertEqual(len(stdout_files), 1)
        self.assertIn("manifest ok", stdout_files[0].read_text(encoding="utf-8"))
        self.assertIn("Manifest runtime", result.report_markdown)

    def test_manifest_rejects_shell_string_commands(self) -> None:
        self.write_manifest(
            {
                "version": 1,
                "app_type": "cli",
                "runtime": "python",
                "checks": [
                    {
                        "name": "bad check",
                        "command": "python app.py && echo done",
                        "timeout_seconds": 30,
                    }
                ],
            }
        )

        result = run_executable_qa(self.app_dir, self.qa_dir)

        self.assertEqual(result.status, "FAIL")
        self.assertIn("command must be a non-empty JSON array", result.error_log)

    def test_manifest_rejects_workdir_outside_generated_app(self) -> None:
        self.write_manifest(
            {
                "version": 1,
                "app_type": "cli",
                "runtime": "python",
                "working_directory": "..",
                "checks": [
                    {
                        "name": "manifest check",
                        "command": [sys.executable, "-c", "print('nope')"],
                        "timeout_seconds": 30,
                    }
                ],
            }
        )

        result = run_executable_qa(self.app_dir, self.qa_dir)

        self.assertEqual(result.status, "FAIL")
        self.assertIn("working_directory must stay inside", result.error_log)

    def test_manifest_without_commands_is_skipped(self) -> None:
        self.write_manifest({"version": 1, "app_type": "cli", "runtime": "python"})

        result = run_executable_qa(self.app_dir, self.qa_dir)

        self.assertEqual(result.status, "SKIP")
        self.assertIn("declares no executable", result.report_markdown)


if __name__ == "__main__":
    unittest.main()
