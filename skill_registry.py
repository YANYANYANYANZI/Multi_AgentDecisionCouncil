from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from state import AgentId


SKILLS_DIR = Path("skills")


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    agent_id: AgentId
    name: str
    version: str
    description: str
    content: str
    references: list[str]
    updated_at: float


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in version.split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class SkillRegistry:
    def __init__(self, skills_dir: Path | str = SKILLS_DIR) -> None:
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, SkillDefinition] = {}
        self.reload()

    def reload(self) -> None:
        self._skills.clear()
        if not self.skills_dir.exists():
            return
        for skill_dir in self.skills_dir.iterdir():
            manifest_path = skill_dir / "manifest.json"
            if not skill_dir.is_dir() or not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            agent_id = manifest["agent_id"]
            entry_point = manifest.get("entry_point", "SKILL.md")
            skill_path = skill_dir / entry_point
            content = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
            references: list[str] = []
            for ref in manifest.get("references", []):
                ref_path = skill_dir / ref
                if ref_path.exists():
                    ref_content = ref_path.read_text(encoding="utf-8")
                    references.append(f"\n\n## 参考资料 · {ref_path.name}\n{ref_content}")
            full_content = f"{content}{''.join(references)}".strip()
            self._skills[manifest["skill_id"]] = SkillDefinition(
                skill_id=manifest["skill_id"],
                agent_id=agent_id,
                name=manifest["name"],
                version=manifest.get("version", "1.0.0"),
                description=manifest.get("description", ""),
                content=full_content,
                references=manifest.get("references", []),
                updated_at=manifest_path.stat().st_mtime,
            )

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def for_agent(self, agent_id: AgentId) -> list[SkillDefinition]:
        items = [skill for skill in self._skills.values() if skill.agent_id == agent_id]
        return sorted(items, key=lambda skill: (_parse_version(skill.version), skill.updated_at, skill.skill_id), reverse=True)

    def latest_for_agent(self, agent_id: AgentId) -> SkillDefinition | None:
        items = self.for_agent(agent_id)
        return items[0] if items else None

    def options_payload(self) -> dict[AgentId, list[dict[str, Any]]]:
        payload: dict[AgentId, list[dict[str, Any]]] = {"S": [], "A": [], "B": [], "C": []}
        for agent_id in payload:
            latest = self.latest_for_agent(agent_id)
            for skill in self.for_agent(agent_id):
                payload[agent_id].append(
                    {
                        "skill_id": skill.skill_id,
                        "agent_id": skill.agent_id,
                        "name": skill.name,
                        "version": skill.version,
                        "description": skill.description,
                        "is_latest": bool(latest and latest.skill_id == skill.skill_id),
                    }
                )
        return payload
