"""Utilities for attaching curated reference packs to agent runs."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REFERENCE_PROFILES: dict[str, str] = {
    "planner_a": "",
    "planner_b": "",
    "code_agent": "karpathy/code_agent",
    "integrator": "karpathy/integrator",
    "qa_agent": "",
}


@dataclass(frozen=True)
class PreparedReferencePack:
    pack_id: str
    source_dir: Path
    run_pack_dir: Path
    role_files: dict[str, Path]
    copied_files: list[Path]


@dataclass(frozen=True)
class PreparedReferenceProfiles:
    role_profiles: dict[str, str]
    packs: dict[str, PreparedReferencePack]
    missing_profiles: dict[str, str]


def normalize_reference_profile(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() in {"none", "off", "false", "0", "disabled"}:
        return ""
    parts = raw.replace("\\", "/").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Reference profile must be empty, none, or pack/role: {value}")
    pack_id, role = parts
    _validate_safe_name(pack_id, "pack")
    _validate_safe_name(role, "role")
    return f"{pack_id}/{role}"


def prepare_reference_profiles(
    project_root: Path,
    run_dir: Path,
    role_profiles: dict[str, str | None],
) -> PreparedReferenceProfiles:
    normalized = {
        role: normalize_reference_profile(profile)
        for role, profile in role_profiles.items()
    }
    pack_ids = sorted(
        {
            pack_id
            for profile in normalized.values()
            for pack_id, _role in [_split_profile(profile)]
            if pack_id
        }
    )
    packs: dict[str, PreparedReferencePack] = {}
    missing: dict[str, str] = {}

    for pack_id in pack_ids:
        prepared = prepare_reference_pack(project_root, run_dir, pack_id)
        if prepared is None:
            for role, profile in normalized.items():
                if profile.startswith(f"{pack_id}/"):
                    missing[role] = profile
            continue
        packs[pack_id] = prepared

    for role, profile in normalized.items():
        if not profile:
            continue
        pack_id, profile_role = _split_profile(profile)
        prepared = packs.get(pack_id)
        if prepared is None or profile_role not in prepared.role_files:
            missing[role] = profile

    return PreparedReferenceProfiles(
        role_profiles=normalized,
        packs=packs,
        missing_profiles=missing,
    )


def prepare_reference_pack(project_root: Path, run_dir: Path, pack_id: str) -> PreparedReferencePack | None:
    """Copy a curated reference pack into one run directory.

    The source pack must be a curated directory under project-root
    reference_packs/. This function never reads or copies ignored vendor source
    caches such as reference_packs/gstack_src/.
    """

    project_root = Path(project_root)
    run_dir = Path(run_dir)
    source_dir = project_root / "reference_packs" / pack_id
    manifest_path = source_dir / "reference_pack_manifest.json"
    if not source_dir.exists() or not manifest_path.exists():
        return None

    manifest = _read_json(manifest_path)
    role_map = manifest.get("default_role_files", {})
    if not isinstance(role_map, dict):
        role_map = {}

    run_pack_dir = run_dir / "reference_packs" / pack_id
    run_pack_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[Path] = []
    role_files: dict[str, Path] = {}

    for extra_name in ["VENDOR.md", "reference_pack_manifest.json"]:
        source_file = source_dir / extra_name
        if source_file.exists():
            dest_file = run_pack_dir / extra_name
            shutil.copy2(source_file, dest_file)
            copied_files.append(dest_file)

    for role, raw_path in role_map.items():
        if not isinstance(role, str) or not isinstance(raw_path, str):
            continue
        source_file = project_root / raw_path
        try:
            source_file.relative_to(source_dir)
        except ValueError:
            if source_file.parent != source_dir:
                continue
        if not source_file.exists() or not source_file.is_file():
            continue
        dest_file = run_pack_dir / source_file.name
        shutil.copy2(source_file, dest_file)
        copied_files.append(dest_file)
        role_files[role] = dest_file

    summary = _render_summary(pack_id, source_dir, run_pack_dir, role_files)
    summary_path = run_pack_dir / "reference_pack_summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    copied_files.append(summary_path)

    return PreparedReferencePack(
        pack_id=pack_id,
        source_dir=source_dir,
        run_pack_dir=run_pack_dir,
        role_files=role_files,
        copied_files=copied_files,
    )


def load_profile_reference_text(
    run_dir: Path,
    profile: str | None,
    *,
    max_chars: int = 12000,
) -> str:
    normalized = normalize_reference_profile(profile)
    if not normalized:
        return ""
    pack_id, role = _split_profile(normalized)
    return load_role_reference_text(run_dir, pack_id, role, max_chars=max_chars)


def load_role_reference_text(
    run_dir: Path,
    pack_id: str,
    role: str,
    *,
    max_chars: int = 12000,
) -> str:
    run_pack_dir = Path(run_dir) / "reference_packs" / pack_id
    manifest_path = run_pack_dir / "reference_pack_manifest.json"
    if not manifest_path.exists():
        return ""

    manifest = _read_json(manifest_path)
    role_map = manifest.get("default_role_files", {})
    if not isinstance(role_map, dict):
        return ""

    raw_path = role_map.get(role)
    if not isinstance(raw_path, str):
        return ""

    reference_path = run_pack_dir / Path(raw_path).name
    if not reference_path.exists():
        return ""

    text = reference_path.read_text(encoding="utf-8").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[truncated]"

    try:
        display_path = reference_path.relative_to(run_dir).as_posix()
    except ValueError:
        display_path = str(reference_path)

    return f"Reference file: {display_path}\n\n{text}"


def _split_profile(profile: str) -> tuple[str, str]:
    if not profile:
        return "", ""
    pack_id, role = profile.split("/", 1)
    return pack_id, role


def _validate_safe_name(value: str, label: str) -> None:
    if not value.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"Reference {label} must contain only letters, numbers, '-' or '_': {value}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _render_summary(pack_id: str, source_dir: Path, run_pack_dir: Path, role_files: dict[str, Path]) -> str:
    lines = [
        f"# Reference Pack: {pack_id}",
        "",
        f"Source directory: `{source_dir}`",
        f"Run copy: `{run_pack_dir}`",
        "",
        "## Role Files",
        "",
    ]
    if not role_files:
        lines.append("- None")
    else:
        for role, path in sorted(role_files.items()):
            lines.append(f"- `{role}`: `{path.name}`")
    lines.extend(
        [
            "",
            "These files are advisory context for Codex agents. They are not",
            "executable skills and should not override run-specific instructions.",
            "",
        ]
    )
    return "\n".join(lines)
