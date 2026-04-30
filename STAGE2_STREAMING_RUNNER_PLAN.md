# Stage 2 Streaming Runner Plan

## Goal

Add an interruptible process runner for Codex-backed workflow stages before
migrating contract, code, integration, and QA execution into the FastAPI worker.

Stage 1 proved that the local API can enqueue planning work and persist worker
state. Stage 2 should make long-running CLI calls observable and cancellable.

## Non-Goals

- Do not migrate the full development pipeline in this stage.
- Do not add a distributed worker or external queue.
- Do not let generated app instructions execute through a shell string.
- Do not make Discord the workflow owner again.

## Current Problem

`codex_runner.py` uses `subprocess.run`, so stdout/stderr are only available
after the process exits. The worker can persist queued/running/completed states,
but it cannot yet:

- show live Codex output,
- record the active child process PID,
- cancel an active Codex subprocess,
- interrupt a run and resume from the latest safe artifact,
- reliably distinguish queued, active, interrupted, cancelled, and failed work.

## Design

Add an async process runner alongside the current synchronous runner.

Recommended shape:

- Keep existing `run_codex_result(...)` for legacy synchronous paths.
- Add `run_codex_result_async(...)` or a new `CodexProcessRunner`.
- Reuse command construction, environment preparation, prompt logging, session
  parsing, and metadata rendering from `codex_runner.py`.
- Use `asyncio.create_subprocess_exec`.
- Pass prompts through stdin.
- Stream stdout and stderr into log files while the process runs.
- Emit worker events for process start, heartbeat, log growth, completion,
  timeout, cancellation, and failure.
- Track PID in `state.json.active_step.pid`.

## State Model

Extend `active_step` only as needed:

```json
{
  "stage": "planning",
  "agent_id": "planner_a",
  "pid": 1234,
  "started_at": "2026-04-30T12:00:00+00:00",
  "interruptible": true
}
```

Continue using `control` for requested actions:

```json
{
  "requested_action": "cancel",
  "feedback": "Stop this run.",
  "requested_by": "local-operator",
  "requested_at": "2026-04-30T12:01:00+00:00"
}
```

Candidate status values:

- `planning_queued`
- `planning_running`
- `awaiting_plan_approval`
- `development_queued`
- `cancelling`
- `cancelled`
- `interrupted`
- `failed`

## Cancellation

Implement two levels.

### Soft Interrupt

Soft interrupt should not kill the process immediately.

Behavior:

- Persist `control.requested_action = "interrupt"`.
- Store feedback.
- Let the current Codex call finish.
- Mark the next checkpoint as requiring user review or revision.
- Resume the agent session when possible.

Use this when the user wants to steer the run but the current step is not
dangerous.

### Hard Cancel

Hard cancel should stop the active process tree.

Behavior:

- Persist `control.requested_action = "cancel"`.
- Set status to `cancelling`.
- Terminate the active child process and descendants.
- Mark the run `cancelled`.
- Clear `active_step`.
- Emit a cancellation event with PID and stage.

Use `psutil` if available. On Windows, fall back to `taskkill /T /F /PID <pid>`
when process-tree termination through Python is not available.

## Worker Integration

Stage 2 should first wire async execution into planning only.

Steps:

1. Add async Codex runner.
2. Update `WorkflowEngine.run_planning` or add an async planning path.
3. Let `RunWorker` call the async planning path directly instead of wrapping
   synchronous work in `asyncio.to_thread`.
4. Persist PID in `active_step`.
5. Add cancel handling while planning is active.
6. Keep `continue_after_plan_approval` as a `development_queued` checkpoint.

## Event Strategy

Append compact events. Do not write every output line into `events.jsonl`.

Suggested events:

- `process_started`
- `process_heartbeat`
- `process_output_updated`
- `process_completed`
- `process_timeout`
- `process_cancel_requested`
- `process_cancelled`
- `process_failed`

The actual stdout/stderr should live in files under `logs/`. Events should
point to the relative artifact path and include byte counts or timestamps.

## UI Strategy

Polling is enough for this stage.

- `/runs/{run_id}` shows current status and `active_step`.
- `/runs/{run_id}/events` shows process and worker events.
- `/runs/{run_id}/artifacts/content?path=logs/...` can show growing logs.

SSE can be added later after the event model is stable.

## Tests

Add tests with a fake command runner before testing with real Codex.

Minimum cases:

- Async runner streams stdout/stderr to files.
- Runner returns a `CodexResult` compatible object.
- Timeout records partial logs.
- Worker stores PID while a job is active.
- Cancel marks queued run cancelled.
- Cancel terminates an active fake long-running process.
- Worker clears `active_step` after success, failure, timeout, and cancel.

## Acceptance Criteria

- `POST /runs` still returns quickly.
- Planning logs grow while Codex is running.
- UI polling can observe queued, running, waiting, failed, and cancelled states.
- Cancel stops an active child process.
- Existing Stage 1 service and UI tests still pass.
- No generated app command is executed through `shell=True`.

## Verification Commands

```bash
python -m py_compile app_services.py local_dashboard_runner.py local_api.py run_local_api.py run_worker.py workflow_engine.py codex_runner.py state_store.py
python -m unittest discover -s tests
cd ux && npm run build
```
