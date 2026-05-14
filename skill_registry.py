"""Local skill registry for prompt-injected agent guidelines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CODE_AGENT_SKILL_ID = "karpathy-guidelines"
MAX_SKILL_CHARS = 12000


@dataclass(frozen=True)
class SkillRecord:
    id: str
    label: str
    source: str
    description: str
    license: str
    relative_path: str
    size_chars: int
    recommended_for: tuple[str, ...] = ()
    variant: str = ""


class SkillRegistry:
    """Discovers curated local skill/guideline files.

    This registry intentionally treats external skills as prompt guidance, not
    native Codex/Claude skill installations.
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def list_skills(self) -> list[SkillRecord]:
        skills: list[SkillRecord] = []
        karpathy = self._karpathy_skill()
        if karpathy is not None:
            skills.append(karpathy)
        skills.extend(self._rules_books_skills())
        return sorted(skills, key=lambda item: (0 if item.id == DEFAULT_CODE_AGENT_SKILL_ID else 1, item.label.lower()))

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        normalized = skill_id.strip()
        if not normalized:
            return None
        for skill in self.list_skills():
            if skill.id == normalized:
                return skill
        return None

    def load_skill_markdown(self, skill_id: str, *, max_chars: int = MAX_SKILL_CHARS) -> str:
        skill = self.get_skill(skill_id)
        if skill is None:
            return ""
        path = self.project_root / skill.relative_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n\n[truncated]"
        header = [
            f"Selected skill: {skill.label}",
            f"Source: {skill.source}",
            f"License: {skill.license}",
            f"Path: {skill.relative_path}",
        ]
        if skill.description:
            header.append(f"Description: {skill.description}")
        return "\n".join(header) + "\n\n" + text

    def _karpathy_skill(self) -> SkillRecord | None:
        candidates = [
            self.project_root
            / "external_skills"
            / "andrej-karpathy-skills-main"
            / "andrej-karpathy-skills-main"
            / "skills"
            / "karpathy-guidelines"
            / "SKILL.md",
            self.project_root / "reference_packs" / "karpathy_src" / "skills" / "karpathy-guidelines" / "SKILL.md",
        ]
        path = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
        if path is None:
            return None
        text = _read_text(path)
        return SkillRecord(
            id=DEFAULT_CODE_AGENT_SKILL_ID,
            label="Karpathy Guidelines",
            source="forrestchang/andrej-karpathy-skills",
            description=_frontmatter_value(text, "description")
            or "Behavioral guidelines for simple, surgical, verifiable coding work.",
            license=_frontmatter_value(text, "license") or "MIT",
            relative_path=_relative_to_project(path, self.project_root),
            size_chars=len(text),
            recommended_for=("code_agent",),
            variant="skill",
        )

    def _rules_books_skills(self) -> list[SkillRecord]:
        root = self.project_root / "external_skills" / "agent-rules-books-main"
        if not root.exists():
            return []
        records: list[SkillRecord] = []
        for path in sorted(root.glob("*/*.md")):
            if not path.is_file():
                continue
            match = re.match(r"(?P<slug>.+)\.(?P<variant>mini|nano)\.md$", path.name)
            if not match:
                continue
            slug = match.group("slug")
            variant = match.group("variant")
            text = _read_text(path)
            label = f"{_title_from_slug(slug)} ({variant})"
            description = _first_nonempty_line_after_heading(text, "When to use")
            records.append(
                SkillRecord(
                    id=f"rules-books/{slug}/{variant}",
                    label=label,
                    source="ciembor/agent-rules-books",
                    description=description or f"{_title_from_slug(slug)} rules distilled for coding agents.",
                    license="MIT",
                    relative_path=_relative_to_project(path, self.project_root),
                    size_chars=len(text),
                    recommended_for=("code_agent",),
                    variant=variant,
                )
            )
        return records


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def _frontmatter_value(text: str, key: str) -> str:
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not match:
        return ""
    field = re.search(rf"^{re.escape(key)}:\s*(.+)$", match.group(1), re.M)
    return field.group(1).strip().strip('"') if field else ""


def _title_from_slug(slug: str) -> str:
    special = {
        "ddd": "DDD",
        "api": "API",
    }
    words = []
    for part in slug.split("-"):
        words.append(special.get(part.lower(), part.capitalize()))
    return " ".join(words)


def _first_nonempty_line_after_heading(text: str, heading: str) -> str:
    lines = text.splitlines()
    needle = f"## {heading}".lower()
    for index, line in enumerate(lines):
        if line.strip().lower() != needle:
            continue
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if stripped and not stripped.startswith("#"):
                return stripped[:240]
    return ""
