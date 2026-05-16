from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_runner import CodexExecutionError, run_codex_result_async


class AsyncCodexRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.logs_dir = self.root / "logs"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def run_fake_codex(self, code: str, *, timeout: float = 5.0, process_started=None):
        with (
            patch("codex_runner._resolve_codex_executable", return_value=sys.executable),
            patch("codex_runner._build_command", return_value=[sys.executable, "-u", "-c", code]),
        ):
            return await run_codex_result_async(
                "prompt text",
                self.root,
                timeout=timeout,  # type: ignore[arg-type]
                logs_dir=self.logs_dir,
                label="fake_codex",
                process_started=process_started,
            )

    async def test_async_runner_streams_stdout_before_process_exits(self) -> None:
        code = "\n".join(
            [
                "import sys, time",
                "print('out-start', flush=True)",
                "print('approval: full-auto', file=sys.stderr, flush=True)",
                "print('sandbox: workspace-write', file=sys.stderr, flush=True)",
                "print('session id: 123e4567-e89b-12d3-a456-426614174000', file=sys.stderr, flush=True)",
                "print('한글 출력', flush=True)",
                "time.sleep(0.4)",
                "print('out-end', flush=True)",
            ]
        )

        task = asyncio.create_task(self.run_fake_codex(code))
        await asyncio.sleep(0.15)

        stdout_files = list(self.logs_dir.glob("*_stdout.txt"))
        self.assertEqual(len(stdout_files), 1)
        partial_stdout = stdout_files[0].read_text(encoding="utf-8")
        self.assertIn("out-start", partial_stdout)
        self.assertIn("한글 출력", partial_stdout)
        self.assertNotIn("out-end", partial_stdout)

        result = await task
        self.assertEqual(result.returncode, 0)
        self.assertIn("out-end", result.stdout)
        self.assertIn("한글 출력", result.stdout)
        self.assertEqual(result.session_id, "123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(result.effective_sandbox, "workspace-write")

    async def test_async_runner_raises_with_streamed_logs_on_nonzero_exit(self) -> None:
        code = "\n".join(
            [
                "import sys",
                "print('before failure', flush=True)",
                "print('failure details', file=sys.stderr, flush=True)",
                "raise SystemExit(7)",
            ]
        )

        with self.assertRaises(CodexExecutionError) as context:
            await self.run_fake_codex(code)

        self.assertEqual(context.exception.returncode, 7)
        self.assertIn("before failure", context.exception.stdout)
        self.assertIn("failure details", context.exception.stderr)
        self.assertIn("before failure", next(self.logs_dir.glob("*_stdout.txt")).read_text(encoding="utf-8"))

    async def test_async_runner_timeout_preserves_partial_logs(self) -> None:
        code = "\n".join(
            [
                "import time",
                "print('partial output', flush=True)",
                "time.sleep(5)",
            ]
        )

        with self.assertRaises(CodexExecutionError) as context:
            await self.run_fake_codex(code, timeout=0.2)

        self.assertIn("timed out", str(context.exception))
        self.assertIn("partial output", context.exception.stdout)
        self.assertIn("partial output", next(self.logs_dir.glob("*_stdout.txt")).read_text(encoding="utf-8"))

    async def test_process_handle_cancel_stops_running_process(self) -> None:
        code = "\n".join(
            [
                "import time",
                "print('ready', flush=True)",
                "time.sleep(10)",
            ]
        )
        handle_box = {}

        def process_started(handle) -> None:
            handle_box["handle"] = handle

        task = asyncio.create_task(self.run_fake_codex(code, process_started=process_started))
        while "handle" not in handle_box:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)

        await handle_box["handle"].cancel(kill_after=0.5)

        with self.assertRaises(CodexExecutionError) as context:
            await task

        self.assertIsNotNone(context.exception.returncode)
        self.assertIn("ready", context.exception.stdout)
        self.assertNotIn("timed out", str(context.exception))


if __name__ == "__main__":
    unittest.main()
