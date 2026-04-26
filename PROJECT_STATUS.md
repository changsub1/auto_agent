# Project Status

## Purpose

This repository is a local Codex CLI multi-agent development automation MVP.
It verifies that a Python orchestrator can call the locally logged-in Codex CLI
instead of using an OpenAI API key or OpenAI SDK directly.

The current system can receive a development request, let multiple Codex-backed
agents discuss the plan, ask a human for approval in Discord, and then generate
a runnable Python app locally.

## Phase 1: Implemented

### Local Codex CLI Integration

- Python calls the local `codex` CLI with `subprocess.run`.
- Prompts are passed through stdin using `codex exec ... -`.
- Shell interpolation is not used.
- Windows Codex launchers such as `codex.cmd` are resolved.
- UTF-8 output handling is configured for Windows.
- Codex calls use:

```text
codex exec --skip-git-repo-check --sandbox workspace-write --color never -
```

### Original CLI MVP

- `main.py` accepts a user request from the terminal.
- Planner Agent creates a planning document.
- Developer Agent generates an app under `runs/<timestamp>/generated_app`.
- QA runs `python -m py_compile` against generated Python files.
- If syntax QA fails, Developer Agent receives the error log and gets one or more fix attempts.

### Discord Human-in-the-loop MVP

- Discord bot entrypoint: `discord_bot.py`
- Slash command: `/dev`
- User can request a service/app from Discord.
- Bot posts progress updates to the Discord channel.
- Planner Agent A creates an initial plan.
- Planner Agent B reviews the plan.
- Planner Agent A creates a final plan.
- Architect Agent creates a contract bundle and task manifest.
- Discord buttons allow the requester to:
  - Approve
  - Request changes
  - Cancel
- If approved, Scaffold Agent creates `scaffold_app`.
- Code Agents implement assigned task groups in isolated workspaces in parallel.
- Integrator Agent merges the work into `generated_app`.
- QA result, generated app path, and executable QA screenshots are posted back
  to Discord when the probe can run.
- After QA, Discord asks the requester to approve the result or request fixes.

### Session and State Management

- Each run creates `runs/YYYYMMDD_HHMMSS`.
- Run state is saved to `state.json`.
- Events are appended to `events.jsonl`.
- Human-readable progress is saved to `transcript.md`.
- Planning artifacts are saved under `planning/`.
- Raw Codex prompt/stdout/stderr/meta logs are saved under `logs/`.
- Codex session IDs are parsed from CLI output and stored per agent.
- Follow-up calls try to resume each agent session with:

```text
codex exec resume <session_id> -
```

- If resume fails, the engine falls back to a fresh Codex call using the latest relevant artifact.
- The full transcript is not resent on every turn.
- Discord progress messages show a short agent session id and whether that call resumed an existing session.

### Current Main Files

- `main.py`: local CLI orchestrator
- `discord_bot.py`: Discord slash command entrypoint
- `dashboard.py`: Streamlit local run control panel for planning/contract/scaffold tests
- `debate_engine.py`: Planner A/B debate, contract approval, parallel development, QA routing
- `agents.py`: Planner, Architect, Scaffold, Code, Integrator, QA, and legacy Developer prompts
- `codex_runner.py`: Codex CLI subprocess wrapper and session parsing
- `parallel_workflow.py`: contract, task assignment, workspace, and merge helpers
- `local_dashboard_runner.py`: local non-Discord planning/contract/scaffold runner
- `state_store.py`: persistent run state and event/transcript storage
- `discord_ui.py`: approval buttons and revision modal
- `discord_reporter.py`: Discord message helpers
- `executable_qa.py`: generated app execution probes, screenshots, and runtime logs
- `qa.py`: mechanical QA result composition and Python syntax QA
- `workspace_manager.py`: run folder and generated app folder helpers
- `config.py`: environment variable configuration

## Known Limitations

- `/dev --medium` or similar per-request model/reasoning selection is not implemented yet.
- Global `CODEX_MODEL` and `CODEX_REASONING_EFFORT` defaults are supported, but Discord per-request model/reasoning selection is not implemented yet.
- Discord messages show planning and QA output, but generated app execution commands are not yet summarized as clearly as they could be.
- QA now has a first executable-probe slice for static HTML, Streamlit, CLI,
  and opt-in Windows launcher checks. Broader GUI automation and app-specific
  assertions are still limited.
- Codex-backed QA Agent review is implemented after mechanical QA. It can use
  the configured QA `CODEX_HOME`, model, reasoning effort, QA report, contract,
  generated app listing, and attached screenshots.
- Session resume is supported, but deeper long-term memory compaction is not implemented.
- Discord approval controls are requester-only, not role/team-policy based.

## Phase 2: Proposed Next Work

### Per-request Model and Reasoning Options

Add support for Discord command options such as:

```text
/dev request:"Build a CSV preview app" reasoning:medium model:gpt-5.5
```

or a lightweight text convention:

```text
/dev --medium Build a CSV preview app
```

Implementation notes:

- Implemented base support for `model` and `reasoning_effort` fields in `CodexResult`.
- Implemented config defaults `CODEX_MODEL` and `CODEX_REASONING_EFFORT`.
- Implemented explicit Codex CLI flags/config overrides in `codex_runner.py`.
- Implemented recording selected model/reasoning in agent session state and Discord status output.
- Remaining work: expose these as true per-request Discord slash command options.

### Better Discord Output

- Post the exact generated app execution command after QA.
- Upload or link `README.md` from `generated_app`.
- Add a `/status run_id` command.
- Add a `/runs` command for recent runs.
- Add a `/cancel run_id` command for long-running tasks.

### Stronger QA

- Add generated app file presence checks.
- Validate `requirements.txt` exists.
- Expand app-specific browser assertions beyond the generic keyboard probe.
- Add Tkinter/Pygame-safe smoke test strategy where practical.
- Expand QA Agent prompts and routing for multiple specialized reviewers.

### Code Review Agent

- Add Code Agent 2 or Reviewer Agent.
- Reviewer checks whether generated code matches the approved plan.
- Reviewer can request Developer Agent revisions before QA.

## Phase 3: Parallel Agent Workflow

Detailed design is tracked in `PARALLEL_AGENT_PLAN.md`.

### Contract-first Parallel Development

- Implemented base Planner/Architect contract bundle before code starts:
  - `requirements.md`
  - `architecture.md`
  - `api_contract.md` or `openapi.yaml`
  - `data_model.md`
  - `task_manifest.json`
  - `file_ownership.md`
  - `acceptance_tests.md`
- Implemented human approval against the contract bundle.
- Implemented Scaffold Agent for the shared project skeleton.
- Implemented Code Agents for isolated task groups in parallel workspaces.
- Implemented Integrator Agent that merges code-agent outputs into the final `generated_app`.
- Implemented first mechanical QA split:
  - Python syntax check
  - executable probe for static HTML, Streamlit, CLI, and opt-in Windows launchers
  - screenshots and runtime logs under `runs/<run_id>/qa/`
  - Codex-backed QA Agent review after mechanical QA
  - targeted fix routing to the owning Code Agent or Integrator
  - Discord QA approval/fix request loop
- Remaining work: add richer app-specific QA agents and stronger structured
  plan-compliance scoring.

### Dynamic Agent and Account Pool

- Support Planner 2-3, Code 1-3, and QA 1-2 agents per run.
- Add an agent registry with:
  - `agent_id`
  - role
  - account assignment
  - `CODEX_HOME`
  - model
  - reasoning effort
  - system/developer prompt override
- Allow two or more local Codex accounts by assigning different `CODEX_HOME`
  directories per account.
- Use account-level concurrency limits so agents can be distributed across
  logged-in accounts.
- Record account/model/reasoning/session details in `state.json`.

### Team Collaboration

- Role-based approval in Discord.
- Multiple approvers.
- Approval audit trail.
- Git branch creation per run.
- Optional automatic commit after approval.

### Dashboard Direction

- Discord becomes a message integration and mobile approval/feedback channel.
- A web dashboard becomes the primary control surface after the core workflow is
  stable.
- Dashboard controls should include agent counts, account pool, model selection,
  reasoning effort, prompt overrides, task assignment, run graph, logs, and
  artifact review.

## Phase 4: Web Dashboard and Integrations

### Web Dashboard

- Build a local dashboard for creating and managing runs.
- Show each stage of a run:
  - planning
  - contract approval
  - scaffold
  - parallel code batches
  - integration
  - QA
  - completion
- Provide forms for:
  - agent count by role
  - model/reasoning per agent
  - account assignment
  - prompt override editing
  - contract review and approval
  - task reassignment before code starts

### Discord Adapter

- Keep `/dev`, `/status`, `/runs`, and approval buttons as a remote control
  layer.
- Send dashboard links or local run paths in Discord status updates.
- Do not make Discord the only place where detailed configuration is possible.

### Framework Evaluation

The current direct orchestrator fits the local Codex CLI constraint well.
AutoGen, LangGraph, or Microsoft Agent Framework can be revisited if:

- workflow state transitions become too complex,
- visual traces are needed,
- checkpointing and resumability exceed the simple `state.json` design,
- or custom Codex CLI model clients become worth maintaining.

LangGraph is the most likely candidate for future workflow orchestration, but
Phase 1 intentionally avoids that dependency.

## Git Sharing Notes

Commit source and documentation files.

Do not commit:

- `runs/`
- `__pycache__/`
- `.pyc` files
- local `.env` files
- Discord bot tokens
- Codex auth/cache directories

Use `.gitignore` to keep generated run artifacts and local caches out of Git.
