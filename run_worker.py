"""In-process FastAPI run worker for local app execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from state_store import StateStore
from workflow_engine import WorkflowEngine


RunJobKind = Literal["start_planning", "continue_after_plan_approval", "revise_plan", "cancel"]


@dataclass(frozen=True)
class RunJob:
    run_id: str
    kind: RunJobKind
    feedback: str = ""
    requested_by: str = "local-operator"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class RunWorker:
    """Small single-process queue for local runs.

    This is intentionally not a distributed worker.  The desktop app owns one
    local FastAPI server, so an in-process queue keeps Stage 1 simple while the
    durable source of truth remains the run directory.
    """

    def __init__(self, project_root: Path, *, engine: WorkflowEngine | None = None) -> None:
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "runs"
        self.engine = engine or WorkflowEngine(self.project_root)
        self._queue: asyncio.Queue[RunJob] | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._queued: dict[str, RunJob] = {}
        self.active_jobs: dict[str, RunJob] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._queue = asyncio.Queue()
        self._stopping = False
        self._loop_task = asyncio.create_task(self._run_loop(), name="run-worker")

    async def stop(self) -> None:
        self._stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None

    async def enqueue(self, job: RunJob) -> None:
        if self._queue is None:
            raise RuntimeError("RunWorker has not been started.")
        if job.kind != "cancel" and (job.run_id in self._queued or job.run_id in self.active_jobs):
            raise ValueError(f"Run {job.run_id} already has a queued or active job.")
        self._queued[job.run_id] = job
        self._append_worker_event(job.run_id, "worker_job_queued", f"{job.kind} queued", job)
        await self._queue.put(job)

    async def wait_idle(self, *, timeout: float = 10.0) -> None:
        """Test helper: wait until the queue and active registry are empty."""

        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            queue_empty = self._queue is None or self._queue.empty()
            if queue_empty and not self._queued and not self.active_jobs:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("RunWorker did not become idle before timeout.")
            await asyncio.sleep(0.02)

    async def _run_loop(self) -> None:
        assert self._queue is not None
        while not self._stopping:
            job = await self._queue.get()
            self._queued.pop(job.run_id, None)
            try:
                await self._run_job(job)
            finally:
                self._queue.task_done()

    async def _run_job(self, job: RunJob) -> None:
        lock = self._locks.setdefault(job.run_id, asyncio.Lock())
        async with lock:
            self.active_jobs[job.run_id] = job
            self._append_worker_event(job.run_id, "worker_job_started", f"{job.kind} started", job)
            try:
                await self._dispatch(job)
                self._append_worker_event(job.run_id, "worker_job_completed", f"{job.kind} completed", job)
            except Exception as exc:  # noqa: BLE001 - worker must persist failures.
                self._record_failure(job, exc)
            finally:
                self.active_jobs.pop(job.run_id, None)

    async def _dispatch(self, job: RunJob) -> None:
        if job.kind == "start_planning":
            await asyncio.to_thread(self.engine.run_planning, job.run_id, feedback=job.feedback or None)
            return
        if job.kind == "revise_plan":
            await asyncio.to_thread(self.engine.run_planning, job.run_id, feedback=job.feedback or None)
            return
        if job.kind == "continue_after_plan_approval":
            await asyncio.to_thread(self.engine.mark_development_queued, job.run_id)
            return
        if job.kind == "cancel":
            await asyncio.to_thread(
                self.engine.mark_cancelled,
                job.run_id,
                requested_by=job.requested_by,
                feedback=job.feedback,
            )
            return
        raise ValueError(f"Unsupported run job kind: {job.kind}")

    def _record_failure(self, job: RunJob, exc: Exception) -> None:
        try:
            store = StateStore(self.runs_root / job.run_id)
            store.set_status("failed")
            store.append_event(
                "worker_job_failed",
                "system",
                f"{job.kind} failed",
                {"error": str(exc), **_job_data(job)},
            )
            store.clear_active_step()
        except Exception:
            return

    def _append_worker_event(self, run_id: str, event_type: str, message: str, job: RunJob) -> None:
        run_dir = self.runs_root / run_id
        if not run_dir.exists():
            return
        StateStore(run_dir).append_event(event_type, "system", message, _job_data(job))


def _job_data(job: RunJob) -> dict[str, Any]:
    return {
        "job_kind": job.kind,
        "requested_by": job.requested_by,
        "feedback": job.feedback,
        "created_at": job.created_at,
    }
