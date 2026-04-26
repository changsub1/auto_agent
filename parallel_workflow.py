"""Helpers for contract-first parallel agent development runs."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONTRACT_FILENAMES = [
    "requirements.md",
    "architecture.md",
    "api_contract.md",
    "data_model.md",
    "task_manifest.json",
    "file_ownership.md",
    "acceptance_tests.md",
    "integration_plan.md",
]


@dataclass(frozen=True)
class CodeAgentAssignment:
    agent_id: str
    codex_home: str | None
    workspace_dir: Path
    tasks: list[dict[str, Any]]

    def to_prompt_json(self) -> str:
        return json.dumps(
            {
                "agent_id": self.agent_id,
                "workspace_dir": str(self.workspace_dir),
                "tasks": self.tasks,
            },
            ensure_ascii=False,
            indent=2,
        )


def create_contract_dir(run_dir: Path) -> Path:
    path = Path(run_dir) / "contract"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_scaffold_dir(run_dir: Path) -> Path:
    return reset_child_dir(Path(run_dir), "scaffold_app")


def create_agent_workspaces_dir(run_dir: Path) -> Path:
    path = Path(run_dir) / "agent_workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_agent_outputs_dir(run_dir: Path) -> Path:
    path = Path(run_dir) / "agent_outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_integration_dir(run_dir: Path) -> Path:
    path = Path(run_dir) / "integration"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_merged_app_dir(run_dir: Path) -> Path:
    integration_dir = create_integration_dir(run_dir)
    return reset_child_dir(integration_dir, "merged_app")


def reset_child_dir(parent: Path, child_name: str) -> Path:
    parent = Path(parent)
    target = parent / child_name
    _assert_within(target, parent)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def copy_tree_contents(source_dir: Path, target_dir: Path) -> None:
    source_dir = Path(source_dir)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        return
    for source in source_dir.iterdir():
        target = target_dir / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def create_agent_workspace(scaffold_dir: Path, workspaces_dir: Path, agent_id: str) -> Path:
    workspace_dir = reset_child_dir(Path(workspaces_dir), agent_id)
    copy_tree_contents(scaffold_dir, workspace_dir)
    return workspace_dir


def reset_generated_app_from_merged(run_dir: Path, merged_app_dir: Path) -> Path:
    generated_app_dir = reset_child_dir(Path(run_dir), "generated_app")
    copy_tree_contents(merged_app_dir, generated_app_dir)
    return generated_app_dir


def normalize_contract_bundle(contract_dir: Path, user_request: str, final_plan: str) -> list[Path]:
    contract_dir = Path(contract_dir)
    contract_dir.mkdir(parents=True, exist_ok=True)

    defaults = _default_contract_files(user_request, final_plan)
    for filename, content in defaults.items():
        path = contract_dir / filename
        if not path.exists() or not path.read_text(encoding="utf-8", errors="replace").strip():
            path.write_text(content, encoding="utf-8")

    tasks = load_task_manifest(contract_dir)
    if not tasks:
        manifest = _fallback_task_manifest(user_request)
        (contract_dir / "task_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return [contract_dir / filename for filename in CONTRACT_FILENAMES if (contract_dir / filename).exists()]


def load_task_manifest(contract_dir: Path) -> list[dict[str, Any]]:
    manifest_path = Path(contract_dir) / "task_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    tasks = payload.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def assign_code_agent_tasks(
    tasks: list[dict[str, Any]],
    *,
    code_agent_count: int,
    code_agent_codex_homes: list[str | None],
    scaffold_dir: Path,
    workspaces_dir: Path,
) -> list[CodeAgentAssignment]:
    usable_tasks = tasks or _fallback_task_manifest("the requested app")["tasks"]
    agent_count = max(1, min(code_agent_count, len(usable_tasks)))
    assignments: list[list[dict[str, Any]]] = [[] for _ in range(agent_count)]

    for index, task in enumerate(usable_tasks):
        assignments[index % agent_count].append(task)

    result: list[CodeAgentAssignment] = []
    for index, assigned_tasks in enumerate(assignments, start=1):
        if not assigned_tasks:
            continue
        agent_id = f"code_{index}"
        codex_home = code_agent_codex_homes[(index - 1) % len(code_agent_codex_homes)] if code_agent_codex_homes else None
        workspace_dir = create_agent_workspace(scaffold_dir, workspaces_dir, agent_id)
        result.append(
            CodeAgentAssignment(
                agent_id=agent_id,
                codex_home=codex_home,
                workspace_dir=workspace_dir,
                tasks=assigned_tasks,
            )
        )
    return result


def build_existing_code_agent_assignments(
    tasks: list[dict[str, Any]],
    *,
    code_agent_count: int,
    code_agent_codex_homes: list[str | None],
    workspaces_dir: Path,
) -> list[CodeAgentAssignment]:
    """Recreate assignment metadata without resetting existing workspaces."""

    usable_tasks = tasks or _fallback_task_manifest("the requested app")["tasks"]
    agent_count = max(1, min(code_agent_count, len(usable_tasks)))
    assignments: list[list[dict[str, Any]]] = [[] for _ in range(agent_count)]

    for index, task in enumerate(usable_tasks):
        assignments[index % agent_count].append(task)

    result: list[CodeAgentAssignment] = []
    for index, assigned_tasks in enumerate(assignments, start=1):
        if not assigned_tasks:
            continue
        agent_id = f"code_{index}"
        codex_home = code_agent_codex_homes[(index - 1) % len(code_agent_codex_homes)] if code_agent_codex_homes else None
        result.append(
            CodeAgentAssignment(
                agent_id=agent_id,
                codex_home=codex_home,
                workspace_dir=Path(workspaces_dir) / agent_id,
                tasks=assigned_tasks,
            )
        )
    return result


def render_contract_bundle(contract_dir: Path) -> str:
    parts: list[str] = []
    for filename in CONTRACT_FILENAMES:
        path = Path(contract_dir) / filename
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        parts.extend([f"## {filename}", "", content or "(empty)", ""])
    return "\n".join(parts).strip()


def seed_merged_app_from_owned_paths(
    assignments: list[CodeAgentAssignment],
    merged_app_dir: Path,
) -> str:
    copied: list[str] = []
    missing: list[str] = []

    for assignment in assignments:
        for task in assignment.tasks:
            for raw_path in _task_path_list(task, "owned_paths"):
                relative_path = _safe_relative_path(raw_path)
                if relative_path is None:
                    missing.append(f"{assignment.agent_id}: unsafe owned path `{raw_path}`")
                    continue
                source = assignment.workspace_dir / relative_path
                target = Path(merged_app_dir) / relative_path
                if not source.exists():
                    missing.append(f"{assignment.agent_id}: `{relative_path.as_posix()}`")
                    continue
                if source.is_dir():
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                copied.append(f"{assignment.agent_id}: `{relative_path.as_posix()}`")

    lines = ["# Merge Seed Report", "", "## Copied owned paths", ""]
    lines.extend(f"- {item}" for item in copied)
    if not copied:
        lines.append("- None")
    lines.extend(["", "## Missing owned paths", ""])
    lines.extend(f"- {item}" for item in missing)
    if not missing:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def render_assignment_summary(assignments: list[CodeAgentAssignment]) -> str:
    lines: list[str] = []
    for assignment in assignments:
        lines.append(f"## {assignment.agent_id}")
        lines.append("")
        lines.append(f"- Workspace: `{assignment.workspace_dir}`")
        lines.append(f"- CODEX_HOME: `{assignment.codex_home or '(default)'}`")
        lines.append("- Tasks:")
        for task in assignment.tasks:
            task_id = str(task.get("id", "(no id)"))
            title = str(task.get("title", task.get("summary", "(untitled)")))
            owned_paths = ", ".join(_task_path_list(task, "owned_paths")) or "(not declared)"
            lines.append(f"  - `{task_id}` {title}; owned paths: {owned_paths}")
        lines.append("")
    return "\n".join(lines).strip()


def list_workspace_files(path: Path) -> str:
    root = Path(path)
    if not root.exists():
        return "(missing)"
    lines = []
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file() and "__pycache__" not in file_path.parts:
            lines.append(file_path.relative_to(root).as_posix())
    return "\n".join(lines) or "(no files)"


def _default_contract_files(user_request: str, final_plan: str) -> dict[str, str]:
    return {
        "requirements.md": f"# Requirements\n\n## User Request\n\n{user_request}\n\n## Approved Plan\n\n{final_plan}\n",
        "architecture.md": "# Architecture\n\nUse a small local Python app with clear module boundaries.\n",
        "api_contract.md": "# API Contract\n\nNo external API is required unless the approved plan explicitly says otherwise.\n",
        "data_model.md": "# Data Model\n\nDefine lightweight Python data structures where useful.\n",
        "file_ownership.md": "# File Ownership\n\nEach task in `task_manifest.json` owns its listed paths.\n",
        "acceptance_tests.md": "# Acceptance Tests\n\nThe generated app should run locally and satisfy the approved plan.\n",
        "integration_plan.md": "# Integration Plan\n\nMerge owned task outputs first, then connect shared entrypoints.\n",
        "task_manifest.json": json.dumps(_fallback_task_manifest(user_request), ensure_ascii=False, indent=2) + "\n",
    }


def _fallback_task_manifest(user_request: str) -> dict[str, Any]:
    return {
        "version": 1,
        "tasks": [
            {
                "id": "T1",
                "title": "Core app implementation",
                "summary": f"Implement the main local Python app behavior for: {user_request}",
                "dependencies": [],
                "owned_paths": ["app.py"],
                "allowed_shared_paths": ["README.md", "requirements.txt"],
                "forbidden_paths": ["contract/", "runs/", "agent_workspaces/"],
                "interfaces": [],
                "acceptance_criteria": ["The app can be launched locally.", "Core user workflow is implemented."],
            },
            {
                "id": "T2",
                "title": "Documentation, dependencies, and tests",
                "summary": "Add run instructions, minimal dependencies, and basic validation tests if practical.",
                "dependencies": [],
                "owned_paths": ["README.md", "requirements.txt", "tests/test_app.py"],
                "allowed_shared_paths": ["app.py"],
                "forbidden_paths": ["contract/", "runs/", "agent_workspaces/"],
                "interfaces": [],
                "acceptance_criteria": ["README includes run commands.", "Dependencies are minimal."],
            },
        ],
    }


def _task_path_list(task: dict[str, Any], key: str) -> list[str]:
    value = task.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).replace("\\", "/").strip() for item in value if str(item).strip()]


def _safe_relative_path(raw_path: str) -> Path | None:
    if not raw_path or raw_path.startswith(("/", "\\")):
        return None
    path = Path(raw_path.replace("\\", "/"))
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _assert_within(path: Path, root: Path) -> None:
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Refusing to operate outside root: {path}") from exc
