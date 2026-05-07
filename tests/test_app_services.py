from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app_services import (
    AgentProviderConfig,
    ArtifactService,
    ConfigService,
    EventService,
    LocalAppSettings,
    ObservationService,
    OperatorActionRequest,
    ProviderService,
    RunCreateRequest,
    RunService,
    SettingsService,
    WorkflowGraph,
    LOCAL_ENV_KEYS,
)
from run_worker import RunWorker
from qa import QAResult
from state_store import StateStore
from workflow_engine import WorkflowEngine


class AppServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.run_dir = self.project_root / "runs" / "20260429_120000"
        self.run_dir.mkdir(parents=True)
        self.store = StateStore(self.run_dir)
        self.store.initialize(
            user_request="Build a local dashboard",
            discord={"source": "unit_test"},
            code_agent_count=2,
            qa_agent_count=1,
        )
        self.store.write_artifact("planning/03_final_plan.md", "# Plan\n", artifact_name="final_plan")
        self.store.append_event("agent_output", "planner_a", "Final plan created", {"path": "planning/03_final_plan.md"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_create_request_validates_routing_mode(self) -> None:
        with self.assertRaises(ValidationError):
            RunCreateRequest(user_request="x", routing_mode="not-a-mode")

    def test_list_runs_returns_state_summary(self) -> None:
        runs = RunService(self.project_root).list_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, "20260429_120000")
        self.assertEqual(runs[0].user_request, "Build a local dashboard")

    def test_create_run_records_route_and_approval_status(self) -> None:
        service = RunService(self.project_root)
        detail = service.create_run(RunCreateRequest(user_request="Build an app", routing_mode="balanced"))
        created_dir = self.project_root / "runs" / detail.run_id

        self.assertEqual(detail.status, "planning_queued")
        self.assertEqual(detail.state["routing"]["mode"], "balanced")
        self.assertEqual(detail.state["workflow"]["resolved_mode"], "balanced")
        self.assertEqual(detail.state["active_step"]["stage"], None)
        self.assertTrue((created_dir / "route.json").exists())

    def test_create_run_records_selected_provider_defaults(self) -> None:
        service = RunService(self.project_root)
        codex_home = str(self.project_root / "account_1")
        detail = service.create_run(
            RunCreateRequest(
                user_request="Build an app",
                routing_mode="fast",
                code_agent_count=1,
                qa_agent_count=1,
                model="gpt-5.5",
                reasoning_effort="high",
                planner_a_codex_home=codex_home,
                planner_b_codex_home=codex_home,
                code_agent_codex_homes=[codex_home],
                qa_agent_codex_homes=[codex_home],
                agent_configs=[
                    AgentProviderConfig(
                        agent_id="planner_a",
                        account="account_1",
                        codex_home=codex_home,
                        model="gpt-5.4",
                        reasoning_effort="xhigh",
                    )
                ],
            )
        )

        dashboard_config = detail.state["dashboard_config"]
        self.assertEqual(dashboard_config["model"], "gpt-5.5")
        self.assertEqual(dashboard_config["reasoning_effort"], "high")
        self.assertEqual(dashboard_config["codex_homes"]["planner_a"], codex_home)
        self.assertEqual(dashboard_config["codex_homes"]["planner_b"], codex_home)
        self.assertEqual(dashboard_config["codex_homes"]["code_agents"], [codex_home])
        self.assertEqual(dashboard_config["codex_homes"]["qa_agents"], [codex_home])
        self.assertEqual(dashboard_config["agent_configs"]["planner_a"]["model"], "gpt-5.4")
        self.assertEqual(dashboard_config["agent_configs"]["planner_a"]["reasoning_effort"], "xhigh")

    def test_settings_service_round_trips_agent_configs(self) -> None:
        service = SettingsService(self.project_root)
        saved = service.save_settings(
            LocalAppSettings(
                default_account="account_1",
                default_codex_home=str(self.project_root / "account_1"),
                default_model="gpt-5.5",
                default_reasoning_effort="high",
                agent_configs=[
                    AgentProviderConfig(
                        agent_id="code_1",
                        account="account_2",
                        codex_home=str(self.project_root / "account_2"),
                        model="gpt-5.4",
                        reasoning_effort="medium",
                    )
                ],
            )
        )
        loaded = service.get_settings()

        self.assertTrue((self.project_root / "local_app_settings.json").exists())
        self.assertEqual(saved.default_model, "gpt-5.5")
        self.assertEqual(loaded.default_account, "account_1")
        self.assertEqual(loaded.agent_configs[0].agent_id, "code_1")
        self.assertEqual(loaded.agent_configs[0].model, "gpt-5.4")

    def test_manual_workflow_graph_is_saved_in_run_state(self) -> None:
        service = RunService(self.project_root)
        graph = WorkflowGraph(
            stages=[
                {"id": "planning", "type": "planning", "agents": ["planner_a"]},
                {"id": "approval_plan", "type": "approval", "after": ["planning"]},
                {"id": "code", "type": "code", "agents": ["code_1"], "after": ["approval_plan"]},
                {"id": "qa", "type": "qa", "agents": ["mechanical_qa"], "after": ["code"]},
                {"id": "approval_qa", "type": "approval", "after": ["qa"]},
            ]
        )
        detail = service.create_run(
            RunCreateRequest(user_request="Build an app", routing_mode="manual", workflow_graph=graph)
        )

        self.assertEqual(detail.state["workflow"]["mode"], "manual")
        self.assertEqual(detail.state["workflow"]["graph"]["stages"][2]["id"], "code")
        self.assertTrue((Path(detail.run_dir) / "workflow_graph.json").exists())

    def test_manual_workflow_graph_rejects_invalid_parallel_code_without_integrator(self) -> None:
        with self.assertRaises(ValidationError):
            RunCreateRequest(
                user_request="Build an app",
                routing_mode="manual",
                workflow_graph={
                    "stages": [
                        {"id": "planning", "type": "planning", "agents": ["planner_a"]},
                        {"id": "approval_plan", "type": "approval", "after": ["planning"]},
                        {
                            "id": "code",
                            "type": "code",
                            "agents": ["code_1", "code_2"],
                            "after": ["approval_plan"],
                            "parallel": True,
                        },
                        {"id": "qa", "type": "qa", "agents": ["mechanical_qa"], "after": ["code"]},
                    ]
                },
            )

    def test_workflow_graph_is_manual_only(self) -> None:
        with self.assertRaises(ValidationError):
            RunCreateRequest(
                user_request="Build an app",
                routing_mode="balanced",
                workflow_graph={
                    "stages": [
                        {"id": "planning", "type": "planning", "agents": ["planner_a"]},
                        {"id": "code", "type": "code", "agents": ["code_1"], "after": ["planning"]},
                    ]
                },
            )

    def test_actions_append_approval_history_and_events(self) -> None:
        service = RunService(self.project_root)
        self.store.set_status("awaiting_plan_approval")
        detail = service.request_changes(
            "20260429_120000",
            OperatorActionRequest(user_id="tester", feedback="Tighten acceptance criteria"),
        )
        self.assertEqual(detail.status, "planning_queued")
        history = detail.state["approval_history"]
        self.assertEqual(history[-1]["action"], "revision_requested")
        self.assertEqual(history[-1]["feedback"], "Tighten acceptance criteria")
        self.assertEqual(detail.state["control"]["requested_action"], "revise_plan")
        events = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("revision_requested", events)

    def test_qa_approval_completes_only_after_qa_approval_checkpoint(self) -> None:
        service = RunService(self.project_root)

        with self.assertRaises(ValueError):
            service.approve_qa("20260429_120000", OperatorActionRequest(user_id="tester"))

        self.store.set_status("awaiting_qa_approval")
        detail = service.approve_qa("20260429_120000", OperatorActionRequest(user_id="tester"))

        self.assertEqual(detail.status, "completed")
        self.assertEqual(detail.state["approval_history"][-1]["action"], "qa_approved")

    def test_qa_fix_request_requires_qa_approval_checkpoint(self) -> None:
        service = RunService(self.project_root)

        with self.assertRaises(ValueError):
            service.request_qa_fix("20260429_120000", OperatorActionRequest(user_id="tester"))

        self.store.set_status("awaiting_qa_approval")
        detail = service.request_qa_fix(
            "20260429_120000",
            OperatorActionRequest(user_id="tester", feedback="Tighten final UI"),
        )

        self.assertEqual(detail.status, "qa_fix_requested")
        self.assertEqual(detail.state["approval_history"][-1]["action"], "qa_fix_requested")

    def test_event_service_maps_jsonl_to_timeline(self) -> None:
        events = EventService(self.project_root).list_events("20260429_120000")
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[-1].who, "Planner A")
        self.assertEqual(events[-1].summary, "# Plan")
        self.assertEqual(events[-1].artifacts[0].path, "planning/03_final_plan.md")

    def test_artifact_service_reads_safe_paths(self) -> None:
        service = ArtifactService(self.project_root)
        artifacts = service.list_artifacts("20260429_120000")
        plan_artifact = next(item for item in artifacts if item.path == "planning/03_final_plan.md")
        self.assertEqual(plan_artifact.type, "file")
        self.assertEqual(plan_artifact.stage, "planning")
        self.assertTrue(plan_artifact.exists)
        self.assertIsNotNone(plan_artifact.updated_at)
        content = service.read_artifact("20260429_120000", "planning/03_final_plan.md")
        self.assertEqual(content.encoding, "utf-8")
        self.assertIn("# Plan", content.content)

    def test_artifact_service_rejects_traversal(self) -> None:
        service = ArtifactService(self.project_root)
        with self.assertRaises(FileNotFoundError):
            service.read_artifact("20260429_120000", "../state.json")

    def test_observation_service_reads_active_step_and_log_tail(self) -> None:
        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir()
        log_path = logs_dir / "planner_a_stdout.txt"
        log_path.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        self.store.set_active_step(stage="planning", agent_id="planner_a", pid=1234, interruptible=True)

        service = ObservationService(self.project_root)
        active_step = service.get_active_step("20260429_120000")
        logs = service.list_logs("20260429_120000")
        tail = service.read_log_tail("20260429_120000", "logs/planner_a_stdout.txt", lines=2)

        self.assertTrue(active_step.active)
        self.assertEqual(active_step.stage, "planning")
        self.assertEqual(active_step.agent_id, "planner_a")
        self.assertEqual(active_step.pid, 1234)
        self.assertEqual(logs[0].path, "logs/planner_a_stdout.txt")
        self.assertEqual(logs[0].stage, "planning")
        self.assertEqual(logs[0].agent_id, "planner_a")
        self.assertEqual(logs[0].stream, "stdout")
        self.assertEqual(tail.content, "line 2\nline 3")
        self.assertTrue(tail.truncated)

    def test_observation_service_rejects_log_path_traversal(self) -> None:
        service = ObservationService(self.project_root)
        with self.assertRaises(FileNotFoundError):
            service.read_log_tail("20260429_120000", "state.json")
        with self.assertRaises(FileNotFoundError):
            service.read_log_tail("20260429_120000", "logs/../state.json")

    def test_config_service_reads_codex_model_defaults(self) -> None:
        codex_home = self.project_root / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            '\n'.join(
                [
                    'profile = "work"',
                    "[profiles.work]",
                    'model = "gpt-5.4"',
                    'model_reasoning_effort = "high"',
                ]
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "CODEX_HOME": str(codex_home),
                "CODEX_MODEL": "",
                "CODEX_REASONING_EFFORT": "",
            },
        ):
            config = ConfigService(self.project_root).get_config()

        self.assertEqual(config.defaults["model"], "gpt-5.4")
        self.assertEqual(config.defaults["reasoning_effort"], "high")
        self.assertEqual(config.defaults["model_source"], "Codex config")

    def test_config_service_loads_codex_homes_from_project_env(self) -> None:
        account_1 = self.project_root / "account_1"
        account_2 = self.project_root / "account_2"
        (self.project_root / ".env").write_text(
            "\n".join(
                [
                    f"CODEX_HOME={account_1}",
                    f"CODE_AGENT_CODEX_HOMES={account_2}",
                    "DISCORD_BOT_TOKEN=should_not_load",
                ]
            ),
            encoding="utf-8",
        )

        saved = {key: os.environ.pop(key, None) for key in [*LOCAL_ENV_KEYS, "DISCORD_BOT_TOKEN"]}
        try:
            config = ConfigService(self.project_root).get_config()
            accounts = [provider["account"] for provider in config.providers if provider["name"] == "Codex"]
            self.assertIn("account_1", accounts)
            self.assertIn("account_2", accounts)
            self.assertNotIn("DISCORD_BOT_TOKEN", os.environ)
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)

    def test_provider_service_parses_codex_model_catalog(self) -> None:
        catalog = {
            "models": [
                {
                    "slug": "gpt-5.4",
                    "display_name": "gpt-5.4",
                    "description": "Strong model",
                    "default_reasoning_level": "medium",
                    "supported_reasoning_levels": [
                        {"effort": "low", "description": "Fast"},
                        {"effort": "high", "description": "Deep"},
                    ],
                    "visibility": "list",
                    "supported_in_api": True,
                }
            ]
        }

        def fake_run(command, **_kwargs):
            self.assertIn("debug", command)
            return subprocess.CompletedProcess(command, 0, json.dumps(catalog), "")

        with patch("app_services.shutil.which", return_value="codex"), patch("app_services.subprocess.run", side_effect=fake_run):
            result = ProviderService(self.project_root).get_codex_models()

        self.assertTrue(result.ok)
        self.assertEqual(result.models[0].id, "gpt-5.4")
        self.assertEqual(result.models[0].default_reasoning_level, "medium")
        self.assertEqual([level.effort for level in result.models[0].supported_reasoning_levels], ["low", "high"])

    def test_provider_service_reports_codex_login_status(self) -> None:
        def fake_run(command, **_kwargs):
            if "--version" in command:
                return subprocess.CompletedProcess(command, 0, "codex-cli 0.124.0\n", "")
            if "status" in command:
                return subprocess.CompletedProcess(command, 0, "Logged in using ChatGPT\n", "")
            return subprocess.CompletedProcess(command, 1, "", "unexpected")

        with patch("app_services.shutil.which", return_value="codex"), patch("app_services.subprocess.run", side_effect=fake_run):
            status = ProviderService(self.project_root).get_codex_status()

        self.assertTrue(status.installed)
        self.assertTrue(status.logged_in)
        self.assertEqual(status.version, "codex-cli 0.124.0")
        self.assertEqual(status.status, "ready")

    def test_provider_service_handles_missing_claude(self) -> None:
        with patch("app_services.shutil.which", return_value=None):
            status = ProviderService(self.project_root).get_claude_status()

        self.assertFalse(status.installed)
        self.assertEqual(status.status, "missing")

    def test_provider_service_reads_codex_rate_limits(self) -> None:
        payload = {
            "rateLimits": {
                "limitId": "codex",
                "primary": {"usedPercent": 41, "windowDurationMins": 300, "resetsAt": 1778057248},
                "secondary": {"usedPercent": 67, "windowDurationMins": 10080, "resetsAt": 1778044493},
                "planType": "plus",
                "rateLimitReachedType": None,
            }
        }

        with patch("app_services.shutil.which", return_value="codex"), patch(
            "app_services._codex_app_server_request", return_value=payload
        ):
            usage = ProviderService(self.project_root).get_runtime_usage()

        self.assertTrue(usage.ok)
        self.assertEqual(usage.source, "codex app-server account/rateLimits/read")
        self.assertEqual(usage.message, "plan: plus")
        self.assertEqual(usage.limits[0].name, "5h limit")
        self.assertEqual(usage.limits[0].used_percent, 41)
        self.assertEqual(usage.limits[0].remaining_percent, 59)
        self.assertEqual(usage.limits[0].window_duration_mins, 300)
        self.assertEqual(usage.limits[1].name, "weekly limit")
        self.assertEqual(usage.limits[1].used_percent, 67)
        self.assertEqual(usage.limits[1].remaining_percent, 33)


class FakeWorkflowEngine:
    def __init__(self, project_root: Path, *, delay: float = 0.0) -> None:
        self.project_root = Path(project_root)
        self.delay = delay
        self.planning_feedback: list[str | None] = []

    def run_planning(self, run_id: str, *, feedback: str | None = None) -> None:
        self.planning_feedback.append(feedback)
        if self.delay:
            time.sleep(self.delay)
        run_dir = self.project_root / "runs" / run_id
        store = StateStore(run_dir)
        store.set_active_step(stage="planning", agent_id="planner_a", interruptible=True)
        store.write_artifact("planning/03_final_plan.md", "# Fake Plan\n", artifact_name="final_plan")
        store.set_status("awaiting_plan_approval")
        store.clear_active_step()

    def mark_development_queued(self, run_id: str) -> None:
        StateStore(self.project_root / "runs" / run_id).set_status("development_queued")

    def mark_cancelled(self, run_id: str, *, requested_by: str = "local-operator", feedback: str = "") -> None:
        store = StateStore(self.project_root / "runs" / run_id)
        store.request_control_action(action="cancel", requested_by=requested_by, feedback=feedback)
        store.set_status("cancelled")


class CancelAwareFakeWorkflowEngine(FakeWorkflowEngine):
    def run_planning(self, run_id: str, *, feedback: str | None = None) -> None:
        self.planning_feedback.append(feedback)
        run_dir = self.project_root / "runs" / run_id
        store = StateStore(run_dir)
        store.set_active_step(stage="planning", agent_id="planner_a", interruptible=True)
        for _ in range(20):
            time.sleep(0.05)
            if store.load().get("status") == "cancelled":
                store.clear_active_step()
                return
        store.write_artifact("planning/03_final_plan.md", "# Fake Plan\n", artifact_name="final_plan")
        store.set_status("awaiting_plan_approval")
        store.clear_active_step()


class FakeProcessHandle:
    pid = 4242

    def __init__(self) -> None:
        self.cancelled = False

    async def cancel(self) -> None:
        self.cancelled = True


class AsyncPlanningFakeWorkflowEngine(FakeWorkflowEngine):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.async_called = False
        self.started_agents: list[str] = []

    async def run_planning_async(self, run_id: str, *, feedback: str | None = None, process_started=None) -> None:
        self.async_called = True
        self.planning_feedback.append(feedback)
        if process_started:
            self.started_agents.append("planner_a")
            process_started("planner_a", FakeProcessHandle())
        await asyncio.sleep(0.01)
        run_dir = self.project_root / "runs" / run_id
        store = StateStore(run_dir)
        store.write_artifact("planning/03_final_plan.md", "# Async Fake Plan\n", artifact_name="final_plan")
        store.set_status("awaiting_plan_approval")
        store.clear_active_step()


class AsyncDevelopmentFakeWorkflowEngine(FakeWorkflowEngine):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.development_called = False
        self.started_processes: list[tuple[str, str]] = []

    async def run_development_async(self, run_id: str, *, process_started=None) -> None:
        self.development_called = True
        if process_started:
            self.started_processes.append(("contract", "architect"))
            process_started("contract", "architect", FakeProcessHandle())
        await asyncio.sleep(0.01)
        run_dir = self.project_root / "runs" / run_id
        store = StateStore(run_dir)
        contract_dir = run_dir / "contract"
        scaffold_dir = run_dir / "scaffold_app"
        contract_dir.mkdir(parents=True, exist_ok=True)
        scaffold_dir.mkdir(parents=True, exist_ok=True)
        store.record_artifact("contract_dir", contract_dir)
        store.record_artifact("scaffold_app", scaffold_dir)
        store.set_status("development_scaffold_completed")
        store.clear_active_step()


class RunWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_create_run_enqueues_planning_and_returns_before_worker_finishes(self) -> None:
        engine = FakeWorkflowEngine(self.project_root, delay=0.2)
        worker = RunWorker(self.project_root, engine=engine)
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = await service.create_run_and_enqueue(RunCreateRequest(user_request="Build an app"))
            immediate = service.get_run(detail.run_id)
            self.assertEqual(immediate.status, "planning_queued")

            await worker.wait_idle(timeout=3)
            final = service.get_run(detail.run_id)
            self.assertEqual(final.status, "awaiting_plan_approval")
            self.assertTrue((Path(final.run_dir) / "planning" / "03_final_plan.md").exists())
        finally:
            await worker.stop()

    async def test_request_changes_enqueues_planning_revision(self) -> None:
        engine = FakeWorkflowEngine(self.project_root)
        worker = RunWorker(self.project_root, engine=engine)
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = service.create_run(RunCreateRequest(user_request="Build an app"))
            StateStore(Path(detail.run_dir)).set_status("awaiting_plan_approval")

            await service.request_changes_and_enqueue(
                detail.run_id,
                OperatorActionRequest(user_id="tester", feedback="Make it smaller"),
            )
            await worker.wait_idle(timeout=3)

            self.assertEqual(engine.planning_feedback[-1], "Make it smaller")
            self.assertEqual(service.get_run(detail.run_id).status, "awaiting_plan_approval")
        finally:
            await worker.stop()

    async def test_duplicate_approval_is_rejected(self) -> None:
        worker = RunWorker(self.project_root, engine=FakeWorkflowEngine(self.project_root))
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = service.create_run(RunCreateRequest(user_request="Build an app"))
            StateStore(Path(detail.run_dir)).set_status("awaiting_plan_approval")

            await service.approve_and_enqueue(detail.run_id, OperatorActionRequest(user_id="tester"))
            with self.assertRaises(ValueError):
                service.approve(detail.run_id, OperatorActionRequest(user_id="tester"))
        finally:
            await worker.stop()

    async def test_cancel_active_job_cancels_registered_process(self) -> None:
        engine = CancelAwareFakeWorkflowEngine(self.project_root)
        worker = RunWorker(self.project_root, engine=engine)
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = await service.create_run_and_enqueue(RunCreateRequest(user_request="Build an app"))
            deadline = time.monotonic() + 3
            while detail.run_id not in worker.active_jobs:
                if time.monotonic() >= deadline:
                    self.fail("worker did not start planning job")
                await asyncio.sleep(0.02)

            handle = FakeProcessHandle()
            worker.register_process(detail.run_id, handle, stage="planning", agent_id="planner_a")

            await service.cancel_and_enqueue(
                detail.run_id,
                OperatorActionRequest(user_id="tester", feedback="Stop this run"),
            )
            await worker.wait_idle(timeout=3)

            final = service.get_run(detail.run_id)
            self.assertTrue(handle.cancelled)
            self.assertEqual(final.status, "cancelled")
            self.assertEqual(final.state["active_step"]["stage"], None)
            self.assertNotIn(detail.run_id, worker.active_processes)
            events = (Path(final.run_dir) / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("active_process_cancel_started", events)
            self.assertIn("active_process_cancelled", events)
        finally:
            await worker.stop()

    async def test_cancel_active_job_cancels_all_registered_processes(self) -> None:
        engine = CancelAwareFakeWorkflowEngine(self.project_root)
        worker = RunWorker(self.project_root, engine=engine)
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = await service.create_run_and_enqueue(RunCreateRequest(user_request="Build an app"))
            deadline = time.monotonic() + 3
            while detail.run_id not in worker.active_jobs:
                if time.monotonic() >= deadline:
                    self.fail("worker did not start planning job")
                await asyncio.sleep(0.02)

            first_handle = FakeProcessHandle()
            second_handle = FakeProcessHandle()
            worker.register_process(detail.run_id, first_handle, stage="code_agents", agent_id="code_1")
            worker.register_process(detail.run_id, second_handle, stage="code_agents", agent_id="code_2")

            await service.cancel_and_enqueue(detail.run_id, OperatorActionRequest(user_id="tester"))
            await worker.wait_idle(timeout=3)

            self.assertTrue(first_handle.cancelled)
            self.assertTrue(second_handle.cancelled)
            self.assertNotIn(detail.run_id, worker.active_processes)
        finally:
            await worker.stop()

    async def test_planning_job_uses_async_engine_and_registers_process(self) -> None:
        engine = AsyncPlanningFakeWorkflowEngine(self.project_root)
        worker = RunWorker(self.project_root, engine=engine)
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = await service.create_run_and_enqueue(RunCreateRequest(user_request="Build an app"))

            await worker.wait_idle(timeout=3)

            final = service.get_run(detail.run_id)
            self.assertTrue(engine.async_called)
            self.assertEqual(engine.started_agents, ["planner_a"])
            self.assertEqual(final.status, "awaiting_plan_approval")
            self.assertEqual(final.state["active_step"]["stage"], None)
            self.assertNotIn(detail.run_id, worker.active_processes)
            events = (Path(final.run_dir) / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("active_step_changed", events)
        finally:
            await worker.stop()

    async def test_approval_job_uses_async_development_engine(self) -> None:
        engine = AsyncDevelopmentFakeWorkflowEngine(self.project_root)
        worker = RunWorker(self.project_root, engine=engine)
        await worker.start()
        try:
            service = RunService(self.project_root, worker=worker)
            detail = service.create_run(RunCreateRequest(user_request="Build an app"))
            StateStore(Path(detail.run_dir)).set_status("awaiting_plan_approval")

            await service.approve_and_enqueue(detail.run_id, OperatorActionRequest(user_id="tester"))
            await worker.wait_idle(timeout=3)

            final = service.get_run(detail.run_id)
            self.assertTrue(engine.development_called)
            self.assertEqual(engine.started_processes, [("contract", "architect")])
            self.assertEqual(final.status, "development_scaffold_completed")
            self.assertEqual(final.state["active_step"]["stage"], None)
            self.assertNotIn(detail.run_id, worker.active_processes)
        finally:
            await worker.stop()


class WorkflowEngineAsyncPlanningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.run_dir = self.project_root / "runs" / "20260430_120000"
        self.run_dir.mkdir(parents=True)
        StateStore(self.run_dir).initialize(user_request="Build an app")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_run_planning_async_records_process_and_reaches_approval(self) -> None:
        async def fake_planning_stage(run_dir, logs_dir, store, config, **kwargs):
            process_started = kwargs.get("process_started")
            if process_started:
                process_started("planner_a", FakeProcessHandle())
            store.write_artifact("planning/03_final_plan.md", "# Async Plan\n", artifact_name="final_plan")
            return {
                "planner_a_draft": "# Draft",
                "planner_review": "# Review",
                "final_plan": "# Async Plan",
            }

        seen_processes = []
        with patch("workflow_engine.run_planning_stage_async", side_effect=fake_planning_stage):
            await WorkflowEngine(self.project_root).run_planning_async(
                "20260430_120000",
                process_started=lambda agent_id, handle: seen_processes.append((agent_id, handle.pid)),
            )

        state = StateStore(self.run_dir).load()
        self.assertEqual(state["status"], "awaiting_plan_approval")
        self.assertEqual(state["active_step"]["stage"], None)
        self.assertEqual(seen_processes, [("planner_a", 4242)])
        self.assertTrue((self.run_dir / "planning" / "03_final_plan.md").exists())


class WorkflowEngineAsyncDevelopmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.run_dir = self.project_root / "runs" / "20260504_120000"
        self.run_dir.mkdir(parents=True)
        store = StateStore(self.run_dir)
        store.initialize(user_request="Build an app")
        store.write_artifact("planning/01_planner_a_draft.md", "# Draft\n", artifact_name="planner_a_draft")
        store.write_artifact("planning/02_planner_b_review.md", "# Review\n", artifact_name="planner_b_review")
        store.write_artifact("planning/03_final_plan.md", "# Final Plan\n", artifact_name="final_plan")
        state = store.load()
        state["routing"] = {
            "requested_mode": "parallel",
            "mode": "parallel",
            "reason": "unit test parallel route",
            "planner_count": 2,
            "code_agent_count": 2,
            "qa_agent_count": 0,
            "pipeline": ["planner_a", "planner_b", "planner_a_final", "architect_contract", "scaffold", "code_agents", "integrator", "mechanical_qa"],
            "uses_contract": True,
            "uses_scaffold": True,
            "uses_integrator": True,
            "uses_llm_qa": False,
        }
        store.save(state)
        store.set_status("development_queued")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_run_development_async_runs_contract_and_scaffold(self) -> None:
        async def fake_contract_stage(run_dir, logs_dir, store, config, plan_artifacts, **kwargs):
            process_started = kwargs.get("process_started")
            if process_started:
                process_started("architect", FakeProcessHandle())
            contract_dir = run_dir / "contract"
            contract_dir.mkdir(parents=True, exist_ok=True)
            (contract_dir / "requirements.md").write_text("# Requirements\n", encoding="utf-8")
            store.record_artifact("contract_dir", contract_dir)
            return contract_dir

        async def fake_scaffold_stage(run_dir, logs_dir, store, config, contract_dir, **kwargs):
            process_started = kwargs.get("process_started")
            if process_started:
                process_started("scaffold", FakeProcessHandle())
            scaffold_dir = run_dir / "scaffold_app"
            scaffold_dir.mkdir(parents=True, exist_ok=True)
            (scaffold_dir / "README.md").write_text("# Scaffold\n", encoding="utf-8")
            store.record_artifact("scaffold_app", scaffold_dir)
            return scaffold_dir

        async def fake_code_agents_stage(run_dir, logs_dir, store, config, contract_dir, scaffold_dir, **kwargs):
            store.set_status("code_agents_running")
            return []

        async def fake_integration_stage(run_dir, logs_dir, store, config, contract_dir, scaffold_dir, assignments, **kwargs):
            process_started = kwargs.get("process_started")
            if process_started:
                process_started("integrator", FakeProcessHandle())
            generated_app_dir = run_dir / "generated_app"
            generated_app_dir.mkdir(parents=True, exist_ok=True)
            store.record_artifact("generated_app", generated_app_dir)
            return generated_app_dir

        def fake_mechanical_qa_stage(run_dir, store, generated_app_dir, **kwargs):
            report_path = run_dir / "qa_report.md"
            report_path.write_text("# QA\n", encoding="utf-8")
            return QAResult(
                ok=True,
                checked_files=[],
                error_log="",
                report_path=report_path,
                report_markdown="# QA\n",
                executable_status="PASS",
                executable_app_type="manifest",
            )

        async def fake_llm_qa_stage(run_dir, logs_dir, store, config, contract_dir, generated_app_dir, mechanical_result, **kwargs):
            return mechanical_result

        seen_processes = []
        with (
            patch("workflow_engine.run_contract_stage_async", side_effect=fake_contract_stage),
            patch("workflow_engine.run_scaffold_stage_async", side_effect=fake_scaffold_stage),
            patch("workflow_engine.run_code_agents_stage_async", side_effect=fake_code_agents_stage),
            patch("workflow_engine.run_integration_stage_async", side_effect=fake_integration_stage),
            patch("workflow_engine.run_mechanical_qa_stage", side_effect=fake_mechanical_qa_stage),
            patch("workflow_engine.run_llm_qa_stage_async", side_effect=fake_llm_qa_stage),
        ):
            await WorkflowEngine(self.project_root).run_development_async(
                "20260504_120000",
                process_started=lambda stage, agent_id, handle: seen_processes.append((stage, agent_id, handle.pid)),
            )

        state = StateStore(self.run_dir).load()
        self.assertEqual(state["status"], "awaiting_qa_approval")
        self.assertEqual(state["active_step"]["stage"], None)
        self.assertEqual(
            seen_processes,
            [("contract", "architect", 4242), ("scaffold", "scaffold", 4242), ("integration", "integrator", 4242)],
        )
        self.assertEqual(state["artifacts"]["contract_dir"], "contract")
        self.assertEqual(state["artifacts"]["scaffold_app"], "scaffold_app")
        self.assertEqual(state["artifacts"]["generated_app"], "generated_app")

    async def test_run_development_async_uses_single_code_route_for_balanced(self) -> None:
        store = StateStore(self.run_dir)
        state = store.load()
        state["routing"] = {
            "requested_mode": "balanced",
            "mode": "balanced",
            "reason": "unit test balanced route",
            "planner_count": 2,
            "code_agent_count": 1,
            "qa_agent_count": 0,
            "pipeline": ["planner_a", "planner_b", "planner_a_final", "code_1", "mechanical_qa"],
            "uses_contract": False,
            "uses_scaffold": False,
            "uses_integrator": False,
            "uses_llm_qa": False,
        }
        store.save(state)

        async def fake_single_code_stage(run_dir, logs_dir, store, config, final_plan, route, **kwargs):
            generated_app_dir = run_dir / "generated_app"
            generated_app_dir.mkdir(parents=True, exist_ok=True)
            store.record_artifact("generated_app", generated_app_dir)
            return generated_app_dir, object(), None

        async def forbidden_contract_stage(*args, **kwargs):
            raise AssertionError("balanced route should not run contract stage")

        def fake_mechanical_qa_stage(run_dir, store, generated_app_dir, **kwargs):
            report_path = run_dir / "qa_report.md"
            report_path.write_text("# QA\n", encoding="utf-8")
            return QAResult(
                ok=True,
                checked_files=[],
                error_log="",
                report_path=report_path,
                report_markdown="# QA\n",
                executable_status="PASS",
                executable_app_type="manifest",
            )

        with (
            patch("workflow_engine.run_single_code_stage_async", side_effect=fake_single_code_stage),
            patch("workflow_engine.run_contract_stage_async", side_effect=forbidden_contract_stage),
            patch("workflow_engine.run_mechanical_qa_stage", side_effect=fake_mechanical_qa_stage),
        ):
            await WorkflowEngine(self.project_root).run_development_async("20260504_120000")

        state = StateStore(self.run_dir).load()
        self.assertEqual(state["status"], "awaiting_qa_approval")
        self.assertEqual(state["artifacts"]["generated_app"], "generated_app")

    async def test_run_development_async_uses_manual_graph_over_stored_route(self) -> None:
        store = StateStore(self.run_dir)
        state = store.load()
        state["workflow"] = {
            "mode": "manual",
            "resolved_mode": "manual",
            "graph": {
                "mode": "manual",
                "stages": [
                    {"id": "planning", "type": "planning", "agents": ["planner_a"], "parallel": False},
                    {"id": "approval_plan", "type": "approval", "after": ["planning"]},
                    {"id": "code", "type": "code", "agents": ["code_1"], "after": ["approval_plan"], "parallel": False},
                    {"id": "qa", "type": "qa", "agents": ["mechanical_qa"], "after": ["code"], "parallel": False},
                    {"id": "approval_qa", "type": "approval", "after": ["qa"]},
                ],
            },
        }
        store.save(state)

        async def fake_single_code_stage(run_dir, logs_dir, store, config, final_plan, route, **kwargs):
            self.assertEqual(route.requested_mode, "manual")
            self.assertEqual(route.code_agent_count, 1)
            self.assertEqual(config.code_agent_count, 1)
            generated_app_dir = run_dir / "generated_app"
            generated_app_dir.mkdir(parents=True, exist_ok=True)
            store.record_artifact("generated_app", generated_app_dir)
            return generated_app_dir, object(), None

        async def forbidden_contract_stage(*args, **kwargs):
            raise AssertionError("single-code manual graph should not run contract stage")

        def fake_mechanical_qa_stage(run_dir, store, generated_app_dir, **kwargs):
            report_path = run_dir / "qa_report.md"
            report_path.write_text("# QA\n", encoding="utf-8")
            return QAResult(
                ok=True,
                checked_files=[],
                error_log="",
                report_path=report_path,
                report_markdown="# QA\n",
                executable_status="PASS",
                executable_app_type="manifest",
            )

        with (
            patch("workflow_engine.run_single_code_stage_async", side_effect=fake_single_code_stage),
            patch("workflow_engine.run_contract_stage_async", side_effect=forbidden_contract_stage),
            patch("workflow_engine.run_mechanical_qa_stage", side_effect=fake_mechanical_qa_stage),
        ):
            await WorkflowEngine(self.project_root).run_development_async("20260504_120000")

        state = StateStore(self.run_dir).load()
        self.assertEqual(state["status"], "awaiting_qa_approval")
        event_text = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("graph_execution_started", event_text)
        self.assertIn("graph_execution_completed", event_text)

    async def test_run_development_async_runs_fix_loop_after_qa_failure(self) -> None:
        async def fake_contract_stage(run_dir, logs_dir, store, config, plan_artifacts, **kwargs):
            contract_dir = run_dir / "contract"
            contract_dir.mkdir(parents=True, exist_ok=True)
            store.record_artifact("contract_dir", contract_dir)
            return contract_dir

        async def fake_scaffold_stage(run_dir, logs_dir, store, config, contract_dir, **kwargs):
            scaffold_dir = run_dir / "scaffold_app"
            scaffold_dir.mkdir(parents=True, exist_ok=True)
            store.record_artifact("scaffold_app", scaffold_dir)
            return scaffold_dir

        async def fake_code_agents_stage(run_dir, logs_dir, store, config, contract_dir, scaffold_dir, **kwargs):
            return []

        async def fake_integration_stage(run_dir, logs_dir, store, config, contract_dir, scaffold_dir, assignments, **kwargs):
            generated_app_dir = run_dir / "generated_app"
            generated_app_dir.mkdir(parents=True, exist_ok=True)
            store.record_artifact("generated_app", generated_app_dir)
            return generated_app_dir

        qa_calls = []

        def fake_mechanical_qa_stage(run_dir, store, generated_app_dir, **kwargs):
            qa_calls.append(kwargs.get("attempt_index"))
            ok = len(qa_calls) > 1
            report_path = run_dir / "qa_report.md"
            report_path.write_text("# QA\n", encoding="utf-8")
            return QAResult(
                ok=ok,
                checked_files=[],
                error_log="" if ok else "broken app",
                report_path=report_path,
                report_markdown="# QA\n",
                executable_status="PASS" if ok else "FAIL",
                executable_app_type="manifest",
                affected_paths=[] if ok else ["src/app.py"],
                suspected_owners=[],
            )

        async def fake_llm_qa_stage(run_dir, logs_dir, store, config, contract_dir, generated_app_dir, mechanical_result, **kwargs):
            return mechanical_result

        fix_calls = []

        async def fake_targeted_fix_stage(run_dir, logs_dir, store, config, contract_dir, scaffold_dir, assignments, qa_result, **kwargs):
            fix_calls.append(kwargs.get("iteration"))
            generated_app_dir = run_dir / "generated_app"
            generated_app_dir.mkdir(parents=True, exist_ok=True)
            return generated_app_dir

        with (
            patch("workflow_engine.run_contract_stage_async", side_effect=fake_contract_stage),
            patch("workflow_engine.run_scaffold_stage_async", side_effect=fake_scaffold_stage),
            patch("workflow_engine.run_code_agents_stage_async", side_effect=fake_code_agents_stage),
            patch("workflow_engine.run_integration_stage_async", side_effect=fake_integration_stage),
            patch("workflow_engine.run_mechanical_qa_stage", side_effect=fake_mechanical_qa_stage),
            patch("workflow_engine.run_llm_qa_stage_async", side_effect=fake_llm_qa_stage),
            patch("workflow_engine.run_targeted_fix_stage_async", side_effect=fake_targeted_fix_stage),
        ):
            await WorkflowEngine(self.project_root).run_development_async("20260504_120000")

        state = StateStore(self.run_dir).load()
        self.assertEqual(state["status"], "awaiting_qa_approval")
        self.assertEqual(qa_calls, [0, 1])
        self.assertEqual(fix_calls, [1])


if __name__ == "__main__":
    unittest.main()
