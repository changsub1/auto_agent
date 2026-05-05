from __future__ import annotations

import unittest
from unittest.mock import patch

import codex_runner


class CodexRunnerCommandTests(unittest.TestCase):
    def test_windows_workspace_write_defaults_to_elevated_sandbox_config(self) -> None:
        with patch("codex_runner.os.name", "nt"), patch.dict("codex_runner.os.environ", {}, clear=True):
            self.assertEqual(codex_runner._windows_sandbox_config("workspace-write"), "elevated")

    def test_windows_read_only_does_not_set_default_windows_sandbox(self) -> None:
        with patch("codex_runner.os.name", "nt"), patch.dict("codex_runner.os.environ", {}, clear=True):
            self.assertEqual(codex_runner._windows_sandbox_config("read-only"), "")

    def test_windows_sandbox_env_override_wins(self) -> None:
        with (
            patch("codex_runner.os.name", "nt"),
            patch.dict("codex_runner.os.environ", {"CODEX_CHILD_WINDOWS_SANDBOX": "custom"}, clear=True),
        ):
            self.assertEqual(codex_runner._windows_sandbox_config("workspace-write"), "custom")


if __name__ == "__main__":
    unittest.main()
