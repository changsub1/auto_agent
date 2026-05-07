# Stage 5C Manual Agent Graph Builder Plan

Stage 5C turns manual mode from a count-based shortcut into an explicit
workflow graph. The user should be able to decide which agents run, which agents
run in parallel, where approval checkpoints happen, and whether integration/QA
stages are required before the run starts.

This stage should preserve the simple `fast`, `balanced`, and `parallel` route
buttons. Manual graph editing is an advanced path layered on top of the Stage5B
provider/account/model/reasoning configuration already implemented.

## Product Goal

Manual mode should answer these questions before a run starts:

- Which stages will execute, and in what order?
- Which agents are assigned to each stage?
- Which stages are parallel groups?
- Where does the user approve or request changes?
- Is an integrator required for the chosen code layout?
- Which QA stages will run after implementation?
- Is the graph valid enough to execute?

The first version should stay pragmatic. It does not need a full visual node
editor immediately. A compact stage list plus path preview is enough if it maps
clearly to the execution model.

## Target Graph Model

The backend should accept a validated graph object on `RunCreateRequest` when
`routing_mode == "manual"`.

```json
{
  "mode": "manual",
  "stages": [
    {
      "id": "planning",
      "type": "planning",
      "agents": ["planner_a", "planner_b"],
      "parallel": false
    },
    {
      "id": "approval_plan",
      "type": "approval",
      "after": ["planning"]
    },
    {
      "id": "code",
      "type": "code",
      "agents": ["code_1", "code_2"],
      "parallel": true
    },
    {
      "id": "integration",
      "type": "integration",
      "agents": ["integrator"],
      "after": ["code"]
    },
    {
      "id": "qa",
      "type": "qa",
      "agents": ["mechanical_qa", "qa_1"],
      "parallel": false
    }
  ]
}
```

### Stage Types

- `planning`: Planner agents create or review the implementation plan.
- `approval`: Human-in-the-loop checkpoint. It does not launch a CLI agent.
- `contract`: Optional architect/contract bundle stage for complex parallel work.
- `scaffold`: Optional scaffold generation stage.
- `code`: One or more code agents implement assigned work.
- `integration`: Integrator merges parallel outputs into `generated_app`.
- `qa`: Mechanical QA and optional LLM QA review.
- `fix`: Optional explicit fix loop stage. The initial implementation can keep
  the existing QA-triggered fix loop instead of exposing this as a user-editable
  stage.

## Stage 5C-1: Schema, Validation, And Preview

Status: implemented as the first manual-graph foundation slice.

Implemented:

- Added backend `WorkflowGraph` and `WorkflowStage` models.
- Added `workflow_graph` to run creation requests for `manual` mode.
- Added backend validation for:
  - duplicate stage ids,
  - missing dependencies,
  - dependency cycles,
  - missing planning/code stages,
  - agent-running stages without agents,
  - parallel approval stages,
  - integration without code,
  - parallel code without an integration stage.
- Manual workflow graphs are saved into run state under `workflow.graph`.
- `workflow_graph.json` is written as a run artifact.
- The roster derives a manual graph from enabled agent cards and shows a compact
  path preview.
- Manual run creation sends the derived graph payload.
- Manual start is blocked when the derived graph has validation warnings.

Still pending:

- Actual graph-based execution is Stage5C-2.
- Freeform stage editing, drag/reorder, and richer graph presets are Stage5C-3.
- Resume/cancel/error hardening is Stage5C-4.

Goal: introduce the graph data model safely without changing the execution
engine yet.

### Backend

1. Add Pydantic models:
   - `WorkflowGraph`
   - `WorkflowStage`
   - `WorkflowStageType`
2. Add `workflow_graph` to `RunCreateRequest`.
3. Validate only when `routing_mode == "manual"` and a graph is supplied.
4. Save the approved graph into `state.json` under `workflow.graph`.
5. Keep the existing manual count-based route execution as a fallback.
6. Add graph validation helpers:
   - unique stage ids,
   - known stage types,
   - required agents for agent-running stages,
   - no missing `after` dependencies,
   - no cycles,
   - approval stages cannot be parallel,
   - integration stages require at least one preceding code stage,
   - parallel code stages with more than one agent require integration or a
     single shared output strategy.
7. Add unit tests for valid and invalid graphs.

### Frontend

1. Derive a default graph from the current manual agent cards.
2. Show a compact path preview above the cards, for example:
   `Planner A + Planner B -> Approval -> Code Agent 1 + Code Agent 2 -> Integrator -> QA`
3. Send `workflow_graph` on manual runs.
4. Show validation warnings before run start.
5. Keep current card add/remove behavior.

### Acceptance

- Manual mode can build and submit a valid graph payload.
- The backend stores the graph in run state.
- Invalid graphs are rejected with useful messages.
- Existing fast/balanced/parallel/manual count flows still work.

## Stage 5C-2: Graph Execution MVP

Status: implemented as a constrained graph execution MVP.

Implemented:

- `WorkflowEngine.run_development_async` detects `workflow.graph` for manual
  runs.
- The engine derives execution counts and route capabilities from the graph
  instead of trusting only the stored route.
- Single-code manual graphs run the single-code development/QA path.
- Parallel-code manual graphs with an integration stage run the existing
  contract/scaffold/code-agents/integration/QA path.
- Graph execution emits boundary events:
  - `graph_execution_started`
  - `graph_stage_started`
  - `graph_stage_completed`
  - `graph_execution_completed`
- Manual-mode added Code/QA/Planner agents now prefer canonical ids such as
  `code_2`, `qa_2`, and `planner_c` so Stage5B per-agent settings line up with
  the runner.

Current constraints:

- The engine still maps graph shapes onto the existing single-code or
  parallel-code pipelines.
- Arbitrary stage DAG execution is not implemented yet.
- Parallel code still uses the existing contract/scaffold prerequisite path.
- Drag/reorder graph editing is still Stage5C-3.

Goal: execute a constrained manual graph using existing workflow functions.

### Backend

1. Add graph execution branch in `workflow_engine.py`:
   - if `routing_mode == "manual"` and `workflow.graph` exists, execute graph.
2. Topologically sort stages by `after`.
3. Map graph stages to existing stage functions:
   - planning -> existing planning stage,
   - approval -> existing plan approval checkpoint,
   - contract/scaffold -> existing optional stages,
   - single-agent code -> single code path,
   - multi-agent parallel code -> parallel code path,
   - integration -> existing integration stage,
   - qa -> existing mechanical/LLM QA path.
4. Record graph-level active step:
   - current stage id,
   - stage type,
   - agent ids,
   - parallel flag.
5. Emit timeline events at stage boundaries:
   - graph stage queued,
   - graph stage started,
   - graph stage completed,
   - graph stage failed.
6. Keep existing QA fix-loop behavior after QA failure.

### Constraints For MVP

- Planning can still use the existing Planner A/B logic.
- Parallel code can reuse the existing assignment and integration path.
- Arbitrary branch/merge DAGs are not required yet.
- Approval checkpoint after planning is required for the first graph execution
  MVP.

### Acceptance

- Manual graph can run:
  `planning -> approval -> code -> qa`
- Manual graph can run:
  `planning -> approval -> code_1 + code_2 parallel -> integration -> qa`
- Run monitor shows graph stage progress in user-configured order.
- QA/fix behavior still works.

## Stage 5C-3: Editable Graph UI

Status: implemented as a stage-card graph editor.

Implemented:

- Manual mode now renders a larger graph editor panel above the agent cards.
- Each graph stage is shown as a stage card, not only a tiny label chip.
- Stage cards list the agents assigned to that stage:
  - `Code Agent 1`
  - `Code Agent 2`
  - `Mechanical QA`
- Parallel stages show an explicit `parallel` badge.
- The graph summary line uses agent names, for example:
  `Planner A, Planner B -> Approval -> Code Agent 1 + Code Agent 2 -> Integrator -> Mechanical QA, QA Agent`.
- Stage cards can be reordered by drag/drop.
- Stage cards can also be moved with compact `‹` and `›` controls.
- Optional integration can be toggled from the graph strip.
- Reset restores the default manual stage order.
- The graph preview uses the edited stage order when creating
  `workflow_graph`.
- Invalid graph shapes still block run start through warnings.

Current constraints:

- This is a horizontal stage-card editor, not a full node canvas.
- Agent-to-stage assignment is still role based:
  - Planner cards feed `planning`.
  - Architect cards feed `contract`.
  - Code cards feed `code`.
  - Integrator feeds `integration`.
  - QA cards feed `qa`.
- Dragging individual agent cards into stages is not implemented yet.
- Named graph preset management is still basic.

Goal: make the manual graph comfortable to edit from the desktop app.

### Frontend

1. Replace manual-only card order assumptions with stage groups.
2. Add simple graph editing actions:
   - add stage,
   - remove stage,
   - move stage earlier/later,
   - add/remove agent from stage,
   - toggle stage parallelism,
   - insert approval checkpoint,
   - toggle contract/scaffold stages,
   - toggle integrator,
   - toggle QA agent review.
3. Render a stage strip above cards:
   - each stage as a compact segment,
   - parallel groups visually grouped,
   - approval checkpoints as distinct markers.
4. Keep cards as the detailed configuration surface.
5. Add graph preset save/load:
   - fast solo,
   - balanced review,
   - parallel two-code,
   - manual custom.

### Acceptance

- User can configure common manual workflows without editing JSON.
- UI prevents obvious invalid graphs before submit.
- Backend validation remains the source of truth.

## Stage 5C-4: Hardening

Goal: make graph mode reliable enough for real use.

### Backend

1. Add more graph tests:
   - duplicate stage ids,
   - missing dependency,
   - cycle,
   - approval in parallel,
   - integration without code,
   - parallel code without integration,
   - unknown agent id,
   - disabled agent referenced by stage.
2. Add state migration/backward compatibility tests.
3. Verify cancellation and resume behavior during graph execution.
4. Verify per-agent Stage5B provider settings still apply inside graph mode.
5. Add clear error messages for unsupported graph shapes.

### Frontend

1. Surface backend validation messages in manual mode.
2. Show stage-level errors in the run monitor.
3. Ensure graph preview remains readable on small screens.
4. Confirm text does not overflow stage chips or agent cards.

## Implementation Order

1. `Stage5C-1`: schema, validation, run-state storage, path preview.
2. `Stage5C-2`: constrained graph execution branch.
3. `Stage5C-3`: editable graph UI.
4. `Stage5C-4`: hardening, resume/cancel/error polish.

## Non-Goals

- No full visual node canvas in the first slice.
- No arbitrary cyclic or conditional workflows.
- No cloud-hosted workflow store.
- No replacement of existing fast/balanced/parallel routes.
- No Claude execution path until a real provider adapter exists.

## Exit Criteria

Stage 5C is complete when:

- Manual mode sends an explicit validated workflow graph.
- The backend rejects invalid graphs with clear messages.
- The graph is saved in run state.
- The workflow engine can execute at least simple and parallel-code manual
  graphs.
- The GUI lets the user edit common graph shapes without JSON.
- Run monitor progress follows the configured graph order.
