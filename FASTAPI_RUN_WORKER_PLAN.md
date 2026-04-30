# FastAPI Run Worker Implementation Plan

This is a temporary working plan. After each major step is implemented and
verified, move the completed summary into `PROJECT_STATUS.md`. Delete this file
after the FastAPI worker migration is complete.

## Goal

Make the local FastAPI API the owner of run execution. The React/Tauri app,
Discord bot, and any future CLI should all call the same service/worker layer.

The first milestone is not to rewrite the whole product at once. It is to add a
safe worker skeleton, move planning execution into it, and make approval actions
enqueue the next stage instead of only mutating state.

## Design Principles

- Keep the API localhost-only.
- Keep long-running Codex calls out of request/response handlers.
- Persist every important transition in `state.json` and `events.jsonl`.
- Preserve existing run artifacts and log conventions.
- Migrate Discord-owned orchestration incrementally.
- Prefer polling first; add SSE after the state/event model is stable.
- Support cancellation and interruption through process management, but start
  with safe state transitions before hard-kill behavior.

## Target Architecture

```text
React/Tauri UI      Discord Bot      CLI
      |                 |             |
      +-----------------+-------------+
                        |
                   RunService
                        |
                   RunWorker
                        |
                 WorkflowEngine
                        |
         Codex process runner + QA runner
                        |
      state.json / events.jsonl / logs / artifacts
```

## Stage 1: Worker Skeleton and Planning Migration

Status: complete for the first worker slice as of 2026-04-30.

Verified:

- `python -m py_compile app_services.py local_dashboard_runner.py local_api.py run_local_api.py run_worker.py workflow_engine.py state_store.py`
- `python -m unittest discover -s tests`
- `npm run build` from `ux/`

The worker now owns local planning execution. Approval currently advances the
run to a `development_queued` checkpoint because contract, code, integration,
and QA migration are intentionally deferred to later stages.

### 1. Add Worker Data Structures

Files:

- `run_worker.py`
- `workflow_engine.py`
- possibly `workflow_models.py`

Tasks:

- Add `RunJob` with:
  - `run_id`
  - `kind`
  - `feedback`
  - `requested_by`
  - `created_at`
- Add job kinds:
  - `start_planning`
  - `continue_after_plan_approval`
  - `revise_plan`
  - `cancel`
- Add in-process `asyncio.Queue`.
- Add active job registry:
  - `run_id -> task`
  - `run_id -> current stage`
- Add per-run `asyncio.Lock`.

Acceptance:

- A run can be queued without blocking the HTTP response.
- Duplicate jobs for the same run are rejected or coalesced safely.
- Worker startup/shutdown hooks are registered in FastAPI lifespan.

### 2. Extend Run State Schema

Files:

- `state_store.py`
- `app_services.py`

Add state fields:

```json
{
  "active_step": {
    "stage": null,
    "agent_id": null,
    "pid": null,
    "started_at": null,
    "interruptible": false
  },
  "control": {
    "requested_action": "none",
    "feedback": "",
    "requested_by": "",
    "requested_at": null
  },
  "workflow": {
    "mode": "balanced",
    "stages": []
  }
}
```

Tasks:

- Add helper methods:
  - `set_active_step(...)`
  - `clear_active_step()`
  - `request_control_action(...)`
  - `clear_control_action()`
  - `set_workflow(...)`
- Keep backward compatibility for older runs that do not have these fields.

Acceptance:

- Old runs still load in the UI.
- New runs include `active_step`, `control`, and `workflow`.
- Events are appended for active step changes and control actions.

### 3. Move Planning Execution Behind WorkflowEngine

Files:

- `workflow_engine.py`
- `local_dashboard_runner.py` or a new planning step module
- `app_services.py`

Tasks:

- Extract reusable planning logic from `local_dashboard_runner.run_local_dashboard_workflow`.
- Keep the first slice focused on `planning_only`.
- `RunService.create_run()` should:
  - create the run directory and initial state quickly,
  - record route/workflow,
  - enqueue `start_planning`,
  - return immediately.
- Worker should execute planning and end in:
  - `awaiting_plan_approval`, or
  - `awaiting_contract_approval` if contract generation is included later.

Acceptance:

- `POST /runs` returns before Codex planning completes.
- UI can poll `/runs/{run_id}` and `/events` to see planning progress.
- Planning artifacts are still written in the same locations.

### 4. Approval Actions Enqueue Next Work

Files:

- `app_services.py`
- `run_worker.py`
- `workflow_engine.py`

Tasks:

- `POST /runs/{run_id}/approve` should:
  - record approval,
  - validate current status,
  - enqueue `continue_after_plan_approval`,
  - return updated state.
- First implementation may set `development_queued` and stop before full
  development migration, but the queue path should exist.
- `POST /runs/{run_id}/request-changes` should enqueue `revise_plan`.
- `POST /runs/{run_id}/cancel` should request cancellation and update state.

Acceptance:

- Approve/request-changes/cancel are idempotent enough for repeated UI clicks.
- Invalid transitions return a clear API error.
- State and events show queued/running/waiting transitions.

### 5. Add Minimal Worker Tests

Files:

- `tests/test_run_worker.py`
- existing service tests

Test cases:

- Create run enqueues planning and returns immediately.
- Worker writes planning status events.
- Request changes enqueues a planning revision job.
- Cancel while queued marks run cancelled.
- Duplicate approval while not waiting is rejected.

## Stage 2: Streaming and Interruptible Codex Runner

Next target. Build this before moving full development and QA execution into the
worker, because later stages need live logs, active process tracking, and real
cancel behavior.

Tasks:

- Add a process runner using `asyncio.create_subprocess_exec` or `subprocess.Popen`.
- Stream stdout/stderr into log files while the process runs.
- Emit heartbeat/progress events.
- Track PID in `active_step`.
- Add hard cancel using process tree termination, preferably with `psutil`.
- Add soft interrupt:
  - store feedback,
  - let current step finish,
  - apply feedback to the next step.
- Add hard interrupt:
  - terminate active process,
  - mark run `interrupted`,
  - resume agent session when possible.

Acceptance:

- UI can show live log growth through artifact polling or event polling.
- Cancel stops active child processes.
- Interrupted runs can be resumed with feedback if a session id is available,
  or restarted from latest artifacts if not.

## Stage 3: Development and QA Migration

Tasks:

- Extract from `debate_engine.py` into `WorkflowEngine`:
  - single-code development
  - parallel scaffold/code/integrator flow
  - mechanical QA
  - LLM QA agents
  - QA revision/fix routing
- Make Discord call the same services instead of owning those methods.

Acceptance:

- App and Discord can both:
  - approve plan/contract,
  - start full code generation,
  - view QA artifacts,
  - approve QA,
  - request QA fixes,
  - cancel active runs.

## Stage 4: Manual Workflow Spec

Tasks:

- Save manual agent layout as a validated workflow spec.
- Support:
  - sequential/parallel stage flag,
  - per-agent account/model/reasoning,
  - role count validation,
  - integration required when code agents > 1,
  - QA required before completion.
- Reject invalid DAGs and cyclic dependencies.

Acceptance:

- Manual mode is not arbitrary free-form execution.
- User can customize within safe workflow templates.

## Stage 5: Project Status Merge

After Stage 1 is implemented:

- Update `PROJECT_STATUS.md` with:
  - worker skeleton completion,
  - planning migration status,
  - new endpoints/behavior,
  - test results,
  - remaining Stage 2+ work.
- Remove completed Stage 1 checklist items or mark them done here.

After the whole worker migration is complete:

- Move any remaining accurate details into `PROJECT_STATUS.md`.
- Delete `FASTAPI_RUN_WORKER_PLAN.md`.
