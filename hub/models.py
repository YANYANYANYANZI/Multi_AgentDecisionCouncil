from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentReply:
    agent_id: str
    agent_name: str
    critical_flaw: str
    key_pivot: str
    reasoning_summary: list[str]
    actionable_blueprint: list[str]
    raw_payload: dict


@dataclass
class RoundRecord:
    user_input: str
    replies: list[AgentReply] = field(default_factory=list)


@dataclass
class BrainstormSession:
    project_name: str = "未命名项目"
    export_dir: str = "exports"
    rounds: list[RoundRecord] = field(default_factory=list)
    reference_docs: list[dict[str, str]] = field(default_factory=list)
