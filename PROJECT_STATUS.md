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
- Discord buttons allow the requester to:
  - Approve
  - Request changes
  - Cancel
- If approved, Developer Agent generates the app.
- QA result and generated app path are posted back to Discord.

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
- `debate_engine.py`: Planner A/B debate, approval handling, developer launch
- `agents.py`: Planner A, Planner B, Developer agent prompts
- `codex_runner.py`: Codex CLI subprocess wrapper and session parsing
- `state_store.py`: persistent run state and event/transcript storage
- `discord_ui.py`: approval buttons and revision modal
- `discord_reporter.py`: Discord message helpers
- `qa.py`: generated Python syntax QA
- `workspace_manager.py`: run folder and generated app folder helpers
- `config.py`: environment variable configuration

## Known Limitations

- `/dev --medium` or similar per-request model/reasoning selection is not implemented yet.
- The Codex CLI currently uses whatever model and reasoning effort are configured in the local Codex environment.
- Discord messages show planning and QA output, but generated app execution commands are not yet summarized as clearly as they could be.
- QA currently checks Python syntax only. It does not run GUI apps, web apps, or end-to-end tests.
- Code Agent 2 and QA Agent are not yet independent LLM agents.
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

- Add `model` and `reasoning_effort` fields to `CodexResult`/state.
- Add config defaults such as `CODEX_MODEL` and `CODEX_REASONING_EFFORT`.
- Pass explicit Codex CLI flags or config overrides from `codex_runner.py`.
- Record selected model/reasoning in `state.json` and Discord status output.

### Better Discord Output

- Post the exact generated app execution command after QA.
- Upload or link `README.md` from `generated_app`.
- Add a `/status run_id` command.
- Add a `/runs` command for recent runs.
- Add a `/cancel run_id` command for long-running tasks.

### Stronger QA

- Add generated app file presence checks.
- Validate `requirements.txt` exists.
- Optionally run CLI apps with `--help` if available.
- Add Streamlit/Tkinter-safe smoke test strategy where practical.
- Add QA Agent as an LLM reviewer after mechanical checks.

### Code Review Agent

- Add Code Agent 2 or Reviewer Agent.
- Reviewer checks whether generated code matches the approved plan.
- Reviewer can request Developer Agent revisions before QA.

## Phase 3: Longer-term Direction

### Richer Multi-agent Workflow

- Add dedicated roles:
  - Product Planner
  - Technical Planner
  - Developer
  - Code Reviewer
  - QA Agent
  - Release/Documentation Agent
- Support multiple planning rounds with compact memory.
- Support state-machine workflow transitions and retries.

### Team Collaboration

- Role-based approval in Discord.
- Multiple approvers.
- Approval audit trail.
- Git branch creation per run.
- Optional automatic commit after approval.

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
