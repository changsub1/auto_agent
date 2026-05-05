from __future__ import annotations

import unittest

from discord_api_engine import _format_run_status, _format_runs_summary, _select_progress_logs


class DiscordApiEngineFormattingTests(unittest.TestCase):
    def test_format_runs_summary_lists_recent_runs(self) -> None:
        message = _format_runs_summary(
            [
                {
                    "run_id": "20260505_010000",
                    "status": "awaiting_qa_approval",
                    "route_mode": "balanced",
                    "updated_at": "2026-05-05T01:00:00+00:00",
                    "user_request": "Build a dashboard",
                }
            ]
        )

        self.assertIn("Recent local runs", message)
        self.assertIn("20260505_010000", message)
        self.assertIn("awaiting_qa_approval", message)

    def test_format_run_status_includes_active_step_and_log_tail(self) -> None:
        message = _format_run_status(
            {
                "run_id": "20260505_010000",
                "status": "code_agents_running",
                "route_mode": "parallel",
                "artifact_count": 3,
                "run_dir": "D:/runs/20260505_010000",
                "user_request": "Build a dashboard",
            },
            active={
                "label": "code_agents, code_1, pid=1234",
                "stage": "code_agents",
                "agent_id": "code_1",
                "pid": 1234,
            },
            logs=[
                {
                    "path": "logs/code_1_stdout.txt",
                    "stream": "stdout",
                    "updated_at": "2026-05-05T01:00:00+00:00",
                }
            ],
            tail={
                "path": "logs/code_1_stdout.txt",
                "content": "implementing files",
            },
        )

        self.assertIn("Run status", message)
        self.assertIn("code_agents_running", message)
        self.assertIn("code_agents, code_1, pid=1234", message)
        self.assertIn("logs/code_1_stdout.txt", message)
        self.assertIn("implementing files", message)

    def test_select_progress_logs_prefers_stderr_then_stdout(self) -> None:
        logs = _select_progress_logs(
            [
                {"path": "logs/a_meta.txt", "stream": "meta", "updated_at": "2026-05-05T01:00:00+00:00"},
                {"path": "logs/a_stdout.txt", "stream": "stdout", "updated_at": "2026-05-05T01:00:00+00:00"},
                {"path": "logs/a_stderr.txt", "stream": "stderr", "updated_at": "2026-05-05T01:00:00+00:00"},
            ]
        )

        self.assertEqual(logs[0]["path"], "logs/a_stderr.txt")
        self.assertEqual(logs[1]["path"], "logs/a_stdout.txt")


if __name__ == "__main__":
    unittest.main()
