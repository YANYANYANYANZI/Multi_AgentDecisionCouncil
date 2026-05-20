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
    team_name: str
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
    def __init__(self, skills_dir: Path | str = SKILLS_DIR, team_name: str | None = None) -> None:
        self.skills_dir = Path(skills_dir)
        self.team_name = team_name.strip() if team_name else None
        self._skills: dict[str, SkillDefinition] = {}
        self._global_constraints = ""
        self.reload()

    def available_teams(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        teams: list[str] = []
        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue
            if (item / "global_constraints.md").exists():
                teams.append(item.name)
                continue
            if any((child / "manifest.json").exists() for child in item.iterdir() if child.is_dir()):
                teams.append(item.name)
        return sorted(set(teams))

    def default_team(self) -> str:
        teams = self.available_teams()
        if "mvp_hacker_team" in teams:
            return "mvp_hacker_team"
        return teams[0] if teams else ""

    def _resolve_team_dir(self) -> Path | None:
        if not self.team_name:
            return None
        team_dir = self.skills_dir / self.team_name
        return team_dir if team_dir.exists() and team_dir.is_dir() else None

    def reload(self) -> None:
        self._skills.clear()
        self._global_constraints = ""
        if not self.skills_dir.exists():
            return
        team_dir = self._resolve_team_dir()
        if team_dir is not None:
            self._global_constraints = (team_dir / "global_constraints.md").read_text(encoding="utf-8").strip() if (team_dir / "global_constraints.md").exists() else ""
            skill_dirs = [item for item in team_dir.iterdir() if item.is_dir()]
            resolved_team_name = team_dir.name
        else:
            skill_dirs = [item for item in self.skills_dir.iterdir() if item.is_dir()]
            resolved_team_name = "__legacy__"

        for skill_dir in skill_dirs:
            manifest_path = skill_dir / "manifest.json"
            if not manifest_path.exists():
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
            prefixed_content = content.strip()
            if self._global_constraints:
                prefixed_content = f"{self._global_constraints}\n\n{prefixed_content}".strip()
            full_content = f"{prefixed_content}{''.join(references)}".strip()
            self._skills[manifest["skill_id"]] = SkillDefinition(
                skill_id=manifest["skill_id"],
                agent_id=agent_id,
                team_name=manifest.get("team_name", resolved_team_name),
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
                        "team_name": skill.team_name,
                        "name": skill.name,
                        "version": skill.version,
                        "description": skill.description,
                        "is_latest": bool(latest and latest.skill_id == skill.skill_id),
                    }
                )
        return payload
