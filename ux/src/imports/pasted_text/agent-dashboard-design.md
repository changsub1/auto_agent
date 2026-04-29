You are a senior product designer designing a modern developer tool dashboard.

Design a desktop-first web dashboard for a local multi-agent development orchestration tool.

This product is used to configure, launch, and monitor multiple AI agents that collaborate on software development tasks through local CLI-based tools such as Codex CLI and possibly Claude. The product is not a consumer chatbot, not a marketing website, and not a generic SaaS admin page. It should feel like a modern developer workbench and agent operations console.

## Product Concept

The system orchestrates multiple AI agents such as:

- Planner A
- Planner B
- Architect
- Designer Agent
- Code Agent 1
- Code Agent 2
- Integrator
- QA Agent

The user can configure which agents are active, assign provider/account/model to each agent, select skill or markdown guidance files, enter a development request, start a run, and monitor the entire workflow.

The core product metaphor is:

- Page 1: Agent Roster / Operator Workbench
- Page 2: ChatOps Run Monitor / Execution Timeline

## Overall Visual Direction

Create a modern developer tool interface.

The interface should feel:

- technical
- precise
- structured
- modern
- compact
- high-signal
- operational
- professional
- calm but not empty
- powerful but not visually noisy

Reference mood conceptually:

- Linear for clean product/development workflow structure
- GitHub Actions for run status, steps, logs, failure diagnosis, and retry
- Slack / Discord for agent conversation flow
- Raycast / Vercel for modern developer tool polish
- Terminal / CLI for compact technical metadata, logs, session IDs, and execution state

Do not directly copy any existing product.

Avoid:

- Apple landing page aesthetic
- huge empty whitespace
- generic admin dashboard look
- playful AI toy style
- social media profile page style
- overly colorful startup UI
- heavy gradients
- excessive glassmorphism
- childish card UI
- marketing-style hero sections
- consumer chat app vibe

This should look like a serious tool for people who operate AI agents and development workflows.

## Theme

Use a light theme first.

Suggested visual language:

- soft neutral background
- white or near-white surfaces
- subtle borders
- compact panels
- crisp typography
- light shadows only when helpful
- functional status colors
- small monospace labels for technical metadata
- slightly rounded but not overly cute corners

Color usage should be restrained. Status colors should communicate meaning, not decoration.

Status colors:

- idle: gray
- ready: blue
- running: indigo or blue
- waiting: amber
- error: red
- done: green
- paused: purple or neutral

## Typography

Use modern developer-tool typography.

Recommended feel:

- clean sans-serif for UI
- slightly technical but readable
- compact metadata
- strong hierarchy
- optional monospace for session IDs, file paths, logs, token/context values

Do not use novelty fonts or futuristic sci-fi fonts.

## Page 1: Agent Roster / Setup Page

Design the first page as the main configuration screen before starting a run.

This page is not a chat page. It is an agent configuration and roster page.

The main purpose is to let the user configure the agent pipeline before execution.

### Page 1 Layout

Use this structure:

1. Left sidebar: global controls
2. Main center area: agent cards arranged in a scrollable grid or canvas
3. Bottom composer: main development request input and run controls

### Left Sidebar Contents

The sidebar should include:

- app name / product logo placeholder
- current workspace or project name
- connected providers / accounts
  - Codex account
  - Claude account
  - optional local profile
- account health or quota summary
  - login status
  - 5-hour limit or usage estimate
  - weekly limit or usage estimate
  - warning state if quota is low
- run mode selector
  - fast
  - balanced
  - parallel
  - manual
- default model selector
- default reasoning level selector
- timeout setting
- retry setting
- saved presets/templates
- button to load previous run

Keep the sidebar compact and tool-like.

### Main Agent Card Area

Show agent cards for the configured workflow.

Example cards:

1. Planner A
2. Planner B
3. Architect
4. Designer Agent
5. Code Agent 1
6. Code Agent 2
7. Integrator
8. QA Agent

The center area should support scrolling because the user may add more agents.

Each agent card should feel like a professional operator card or capability module, not a social media profile card.

Each card should display:

- agent name
- role
- short description of responsibility
- capability tags
- provider: Codex / Claude / Manual / Local
- account/profile
- model
- reasoning level
- assigned skill or markdown guidance file
- status badge
- context/session health
- current session ID or placeholder
- last action summary
- controls:
  - settings
  - duplicate
  - delete
  - enable/disable

Example card content:

Planner A
Role: Requirement Analysis
Provider: Codex
Model: gpt-5-codex
Skill: planner.md
Status: Ready
Context: 72% left
Capabilities: Planning / Risk Check / Spec Draft

Code Agent 1
Role: Frontend Implementation
Provider: Codex
Model: gpt-5-codex
Skill: frontend.md
Status: Idle
Context: New Session
Capabilities: React / UI / State Logic

QA Agent
Role: Execution & Visual QA
Provider: Claude
Model: Opus
Skill: qa-review.md
Status: Waiting
Context: 85% left
Capabilities: Run Test / Screenshot Review / Error Report

Do not show long outputs inside the agent cards. Cards are for overview and configuration only.

### Agent Actions

Provide clear UI affordances for:

- Add Agent
- Remove Agent
- Duplicate Agent
- Reorder workflow
- Change provider/account/model
- Attach markdown skill/reference file
- Toggle agent active/inactive
- Reset session
- Continue previous session

The “Add Agent” action should feel natural. It can be a large empty card with a plus button or a floating action button inside the agent grid.

When adding an agent, show agent type options such as:

- Planner
- Architect
- Designer
- Code Agent
- Integrator
- QA Agent
- Custom Agent

### Workflow Ordering

Represent the workflow order visually.

The user should understand that agents execute in a pipeline.

However, allow the visual design to support both sequential and parallel groups.

Example:

1. Planner A
2. Planner B
3. Architect
4. Designer Agent
5. Code Agent 1 + Code Agent 2 in parallel
6. Integrator
7. QA Agent

Show this in a simple visual way without making the UI too complicated.

### Bottom Composer

At the bottom of Page 1, design a prompt input area similar to a developer command composer.

It should include:

- large prompt input box
- placeholder text: “Describe the app or feature you want the agents to build…”
- file attachment button
- skill/reference file attachment
- continue existing run option
- primary button: Start Run
- secondary button: Save Preset

The composer should feel like a serious developer input area, not a casual chatbot input.

## Page 2: Run Monitor / ChatOps Page

Design the second page as the active execution monitor after the run starts.

This page is not just a chat app. It is a ChatOps-style execution monitor where agent conversations, workflow states, logs, approvals, and artifacts are shown together.

### Page 2 Layout

Use this structure:

1. Top bar: run summary and controls
2. Left panel: compact agent status list
3. Center panel: conversation / event timeline
4. Right panel or details drawer: selected message details, logs, artifacts, QA report

### Top Bar Contents

The top bar should show:

- run ID
- project name
- current phase
- elapsed time
- run status
- context risk summary
- quota warning if needed
- controls:
  - pause
  - stop
  - retry
  - approve
  - request changes
  - open output folder

Example top bar:

Run: 20260428_143200
Status: Waiting for approval
Phase: Planner Review
Elapsed: 04:32
Context Risk: Low
Actions: Pause / Stop / Approve / Request Changes

### Left Agent Status Panel

Show all agents in compact list form.

Each row should include:

- agent name
- role icon or small marker
- status
- elapsed thinking/running time
- context remaining
- session state
- last event

Example rows:

Planner A — Done — 01:12 — Context 68%
Planner B — Reviewing — 00:43 — Context 81%
Architect — Waiting — New session
Code Agent 1 — Queued
Code Agent 2 — Queued
QA Agent — Queued

The user should quickly understand who is active, who is waiting, and who failed.

### Center Timeline / ChatOps Stream

The center should show a professional timeline/chat hybrid.

It should show messages and events such as:

- System created run
- Planner A proposed plan
- Planner B reviewed the plan
- Architect generated contract bundle
- System requested user approval
- User approved
- Code Agent 1 started frontend implementation
- Code Agent 2 started backend implementation
- Integrator merged outputs
- QA Agent ran syntax check
- QA Agent captured screenshot
- QA failed / passed
- Artifacts generated

Each timeline item should show:

- agent/system identity
- timestamp
- status marker
- message title
- summary
- collapsible details
- artifact links if any

Long outputs should be collapsible by default.

Use realistic placeholder timeline messages.

Example timeline messages:

[Planner A]
Initial development plan created.
Summary:
- Build a two-page dashboard
- Implement agent roster configuration
- Add ChatOps run monitor
- Store run settings as JSON
- Use mock runner before connecting real CLI

[Planner B]
Review completed.
Findings:
- Add approval checkpoint before code generation
- Separate visual agent order from execution pipeline order
- Add context-risk state to each session

[System]
Approval required before implementation.

[User]
Approved. Proceed with implementation.

[Code Agent 1]
Frontend implementation started.
Files:
- DashboardLayout.tsx
- AgentRosterPage.tsx
- AgentCard.tsx

[QA Agent]
QA check failed.
Issue:
- Agent card overflow on small desktop width
Action:
- Requesting layout fix

### Right Detail / Artifact Panel

Design a right panel or drawer for inspecting details.

It should show:

- selected timeline message details
- generated files
- plan files
- contract files
- QA report
- screenshots
- logs
- stdout/stderr
- file paths
- run_config.json
- events.jsonl
- transcript.md

Example artifact panel sections:

- Current Selection
- Artifacts
- Logs
- Screenshots
- QA Report
- Generated App
- Open Folder

Keep it technical but readable.

## Required Components

Create a reusable component system for:

1. App shell
2. Left sidebar
3. Provider/account summary card
4. Run mode selector
5. Agent card
6. Status badge
7. Context/session health indicator
8. Agent add card
9. Workflow order indicator
10. Prompt composer
11. Top run bar
12. Agent status row
13. Timeline item
14. Approval checkpoint
15. Artifact panel
16. Log viewer
17. Action buttons

## Interaction States to Represent

Please include realistic UI states:

- idle
- ready
- queued
- running
- thinking
- waiting for approval
- paused
- error
- done
- context risk high
- quota warning
- session resumed
- new session created

## Dynamic Behavior to Prototype

If possible, design simple prototype interactions:

Page 1:
- clicking “Add Agent” opens an agent type selection panel
- clicking an agent card opens settings
- clicking “Start Run” navigates to Page 2
- workflow order can be visually understood

Page 2:
- clicking a timeline item updates the artifact/detail panel
- approval checkpoint shows Approve / Request Changes / Cancel
- long outputs can be expanded/collapsed
- failed QA item visually stands out
- stop/pause/retry actions are visible

## Content Style

Use concise technical UI labels.

Good labels:

- Waiting for approval
- QA failed
- Session resumed
- Context risk: high
- 3 artifacts generated
- Retry from step
- Open output folder
- Attach skill file
- Start run
- Continue session
- Provider status
- Run preset

Avoid cute copy, emotional chatbot phrases, or marketing slogans.

## Density and Spacing

This is a tool for technical users.

The UI can be moderately dense, but should never feel cramped.

Prefer:

- clear grouping
- compact metadata
- subtle borders
- predictable spacing
- readable panels
- strong hierarchy
- consistent status indicators

## Final Design Requirements

Design two high-fidelity desktop pages:

1. Agent Roster / Setup Page
2. Run Monitor / ChatOps Page

The pages should feel like they belong to the same product.

Use realistic placeholder data.

Make the design implementation-friendly for a React dashboard.

Focus on clarity, workflow visibility, and agent operations.

Do not ask follow-up questions. Make reasonable design assumptions and produce the best complete design you can.