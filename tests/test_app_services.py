from __future__ import annotations

import asyncio
import json
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app_services import (
    ArtifactService,
    ConfigService,
    EventService,
    OperatorActionRequest,
    RunCreateRequest,
    RunService,
    LOCAL_ENV_KEYS,
)
from run_worker import RunWorker
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

    def test_event_service_maps_jsonl_to_timeline(self) -> None:
        events = EventService(self.project_root).list_events("20260429_120000")
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[-1].who, "Planner A")
        self.assertEqual(events[-1].artifacts[0].path, "planning/03_final_plan.md")

    def test_artifact_service_reads_safe_paths(self) -> None:
        service = ArtifactService(self.project_root)
        artifacts = service.list_artifacts("20260429_120000")
        self.assertTrue(any(item.path == "planning/03_final_plan.md" for item in artifacts))
        content = service.read_artifact("20260429_120000", "planning/03_final_plan.md")
        self.assertEqual(content.encoding, "utf-8")
        self.assertIn("# Plan", content.content)

    def test_artifact_service_rejects_traversal(self) -> None:
        service = ArtifactService(self.project_root)
        with self.assertRaises(FileNotFoundError):
            service.read_artifact("20260429_120000", "../state.json")

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


if __name__ == "__main__":
    unittest.main()
