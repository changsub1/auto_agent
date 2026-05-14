from __future__ import annotations

import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_runner import CodexResult
from local_dashboard_runner import LocalRunConfig, run_llm_qa_stage_async
from qa import QAResult
from state_store import StateStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _config() -> LocalRunConfig:
    return LocalRunConfig(
        user_request="Build a small browser app.",
        run_mode="full_run",
        planner_count=2,
        code_agent_count=1,
        qa_agent_count=1,
        planner_a_codex_home=None,
        planner_b_codex_home=None,
        planner_c_codex_home=None,
        architect_codex_home=None,
        scaffold_codex_home=None,
        integrator_codex_home=None,
        code_agent_codex_homes=[],
        qa_agent_codex_homes=[],
        model=None,
        reasoning_effort=None,
        agent_configs={},
        prompt_overrides={},
        max_fix_iterations=1,
        timeout_seconds=60,
    )


class QAWorkspaceAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        shutil.copytree(PROJECT_ROOT / "qa_tools", self.project_root / "qa_tools")
        self.run_dir = self.project_root / "runs" / "20260514_120000"
        self.run_dir.mkdir(parents=True)
        self.logs_dir = self.run_dir / "logs"
        self.logs_dir.mkdir()
        self.generated_app = self.run_dir / "generated_app"
        self.generated_app.mkdir()
        (self.generated_app / "index.html").write_text("<main>Hello</main>", encoding="utf-8")
        self.contract_dir = self.run_dir / "contract"
        self.contract_dir.mkdir()
        self.store = StateStore(self.run_dir)
        self.store.initialize(user_request="Build a small browser app.", qa_agent_count=1)
        self.qa_report = self.run_dir / "qa_report.md"
        self.qa_report.write_text("# Mechanical QA\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _mechanical_result(self, *, app_type: str = "static_html") -> QAResult:
        return QAResult(
            ok=True,
            checked_files=[],
            error_log="",
            report_path=self.qa_report,
            report_markdown="# Mechanical QA\n",
            screenshots=[],
            artifact_paths=[],
            executable_status="PASS",
            executable_app_type=app_type,
        )

    async def test_workspace_agent_copies_app_and_accepts_evidence_verdict(self) -> None:
        async def fake_run_codex(prompt, workdir, **kwargs):
            workdir = Path(workdir)
            (workdir / "screenshots" / "initial.png").write_bytes(b"png")
            (workdir / "evidence" / "qa_findings.md").write_text("# Findings\n\nLooks good.\n", encoding="utf-8")
            (workdir / "evidence" / "command_log.jsonl").write_text(
                '{"command":["probe"],"exit_code":0}\n',
                encoding="utf-8",
            )
            (workdir / "evidence" / "verdict.json").write_text(
                (
                    '{\n'
                    '  "status": "PASS",\n'
                    '  "summary": "Evidence supports the requested behavior.",\n'
                    '  "findings": ["none"],\n'
                    '  "evidence": ["screenshots/initial.png"],\n'
                    '  "affected_paths": ["none"],\n'
                    '  "suspected_owners": ["none"]\n'
                    '}\n'
                ),
                encoding="utf-8",
            )
            return CodexResult(
                stdout="QA_STATUS: PASS\n",
                stderr="",
                returncode=0,
                session_id="session-1",
                resumed_session_id=None,
                model=None,
                reasoning_effort=None,
                effective_approval="never",
                effective_sandbox="workspace-write",
            )

        with patch("agents.run_codex_result_async", side_effect=fake_run_codex):
            result = await run_llm_qa_stage_async(
                self.run_dir,
                self.logs_dir,
                self.store,
                _config(),
                self.contract_dir,
                self.generated_app,
                self._mechanical_result(),
            )

        workspace = self.run_dir / "qa" / "attempt_00" / "qa_workspace"
        self.assertTrue((workspace / "app" / "index.html").exists())
        self.assertTrue((workspace / "qa_tools" / "browser_probe.py").exists())
        self.assertTrue((workspace / "qa_tools" / "browser_probe.cmd").exists())
        launcher = (workspace / "qa_tools" / "browser_probe.cmd").read_text(encoding="utf-8")
        self.assertIn("PYTHONUTF8=1", launcher)
        self.assertIn("browser_probe.py", launcher)
        self.assertTrue(result.ok)
        self.assertIn("Codex QA Workspace Agent Reviews", result.report_markdown)
        self.assertIn(workspace / "screenshots" / "initial.png", result.screenshots)

    async def test_visual_app_pass_is_downgraded_without_screenshot_evidence(self) -> None:
        async def fake_run_codex(prompt, workdir, **kwargs):
            workdir = Path(workdir)
            (workdir / "evidence" / "qa_findings.md").write_text("# Findings\n\nNo screenshot.\n", encoding="utf-8")
            (workdir / "evidence" / "verdict.json").write_text(
                (
                    '{\n'
                    '  "status": "PASS",\n'
                    '  "summary": "Looks good without visual evidence.",\n'
                    '  "findings": ["none"],\n'
                    '  "evidence": ["evidence/qa_findings.md"],\n'
                    '  "affected_paths": ["none"],\n'
                    '  "suspected_owners": ["none"]\n'
                    '}\n'
                ),
                encoding="utf-8",
            )
            return CodexResult(
                stdout="QA_STATUS: PASS\n",
                stderr="",
                returncode=0,
                session_id="session-1",
                resumed_session_id=None,
                model=None,
                reasoning_effort=None,
                effective_approval="never",
                effective_sandbox="workspace-write",
            )

        with patch("agents.run_codex_result_async", side_effect=fake_run_codex):
            result = await run_llm_qa_stage_async(
                self.run_dir,
                self.logs_dir,
                self.store,
                _config(),
                self.contract_dir,
                self.generated_app,
                self._mechanical_result(app_type="static_html"),
            )

        self.assertFalse(result.ok)
        self.assertIn("screenshot evidence", result.error_log)
        verdict = (self.run_dir / "qa" / "attempt_00" / "qa_workspace" / "evidence" / "verdict.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"status": "FAIL"', verdict)


if __name__ == "__main__":
    unittest.main()
