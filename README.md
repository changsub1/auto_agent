# Local Codex Multi-Agent Development MVP

This project is a local technical MVP for multi-agent development automation.
It does not use an OpenAI API key directly and does not use the OpenAI SDK.
All LLM work is delegated to the locally installed and logged-in Codex CLI
through Python `subprocess`.

The original CLI flow is still available:

```text
User request -> Planner Agent -> Developer Agent -> Python syntax QA
```

The new Discord flow adds human-in-the-loop planning approval:

```text
/dev request
  -> Planner Agent A draft
  -> Planner Agent B review
  -> Planner Agent A final plan
  -> Discord approve / request changes / cancel
  -> Developer Agent creates app
  -> Python syntax QA
```

## Requirements

- Python 3.10 or newer
- Codex CLI installed and logged in locally
- For Discord mode: a Discord bot token

Check Codex CLI first:

```bash
codex --help
codex exec --help
codex login status
```

## Install Python Dependencies

```bash
cd multi_codex_dev_mvp
python -m pip install -r requirements.txt
```

`requirements.txt` only contains Discord bot dependencies. Codex itself must be
installed separately and available as `codex` on PATH.

## Local CLI Usage

```bash
python main.py "CSV file upload app that previews rows and shows missing value counts."
```

Planner and Developer can use different `CODEX_HOME` values:

```bash
python main.py --planner-codex-home "C:\Users\USER\.codex_planner" --developer-codex-home "C:\Users\USER\.codex_developer" "Build a simple todo app."
```

Set syntax-fix retries:

```bash
python main.py --max-fix-iterations 1 "Build a CSV analysis app."
```

## Discord Bot Usage

Set environment variables:

```bat
set DISCORD_BOT_TOKEN=your_bot_token
set DISCORD_GUILD_ID=your_test_guild_id
```

Optional controls:

```bat
set DISCORD_ALLOWED_CHANNEL_ID=channel_id
set DISCORD_ALLOWED_USER_IDS=user_id_1,user_id_2
set PLANNER_A_CODEX_HOME=C:\Users\USER\.codex_planner_a
set PLANNER_B_CODEX_HOME=C:\Users\USER\.codex_planner_b
set DEVELOPER_CODEX_HOME=C:\Users\USER\.codex_developer
set MAX_FIX_ITERATIONS=1
set CODEX_TIMEOUT_SECONDS=900
```

Run the bot:

```bash
python discord_bot.py
```

In Discord:

```text
/dev CSV file upload app that previews data and shows missing value counts.
```

The bot posts Planner A's draft, Planner B's review, and the final plan. The
requesting user then gets buttons:

- Approve
- Request changes
- Cancel

Approval starts the Developer Agent. A revision request sends the feedback back
into the planning loop.

## Run Output

Each run creates a timestamped directory:

```text
runs/YYYYMMDD_HHMMSS/
  state.json
  events.jsonl
  transcript.md
  plan.md
  planning/
    01_planner_a_draft.md
    02_planner_b_review.md
    03_final_plan.md
  generated_app/
    app.py
    requirements.txt
    README.md
  qa_report.md
  logs/
    *_prompt.txt
    *_stdout.txt
    *_stderr.txt
    *_meta.txt
```

## Session and Memory Design

The Discord workflow is session-oriented.

- Each agent has its own Codex session id in `state.json`.
- New agent calls use `codex exec ... -`.
- Follow-up calls try `codex exec resume <session_id> -`.
- Prompts are sent through stdin, not shell interpolation.
- If resume fails, the engine falls back to a fresh Codex call using the latest
  relevant artifact instead of the full transcript.

Local files are still written for audit and recovery:

- `state.json`: current run status, Discord ids, artifact paths, agent session ids
- `events.jsonl`: append-only machine-readable event log
- `transcript.md`: human-readable conversation and artifact log
- `planning/*.md`: planning artifacts
- `logs/*`: raw Codex prompt/stdout/stderr/meta logs

The engine intentionally avoids sending the full transcript on every turn. It
prefers Codex session resume and only sends the new feedback, review, or latest
artifact needed for that turn.

## Safety Notes

- User requests are never executed as shell commands.
- User requests are passed only as Codex prompt text through stdin.
- `subprocess.run` uses list arguments and `shell=False`.
- Codex calls use `--skip-git-repo-check`.
- New Codex exec calls use `--sandbox workspace-write`.
- Generated apps are created under each run's `generated_app` directory.
- Generated `.bat` and `.cmd` files are normalized to CRLF line endings.

## Syntax Check

```bash
python -m py_compile main.py agents.py codex_runner.py workspace_manager.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py
```
