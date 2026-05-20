from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, messages_from_dict, messages_to_dict
from openai import OpenAI
from pydantic import BaseModel, Field

from agents import (
    AGENT_SPECS,
    DEFAULT_JUDGE_PROMPT,
    build_agent_ai_message,
    build_judge_ai_message,
    configure_agents,
    decision_memory_from_judge_output,
    generate_export_bundle,
    get_agent_spec,
    merge_decision_memory,
    node_summarizer,
    run_judge,
    stream_agent_reply,
)
from graph import build_graph
from hub.config import load_settings
from skill_registry import SkillRegistry
from state import AgentId, DecisionMemory, RoundMode, TaskBrief

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None


MODEL_REGISTRY = [
    {"id": "deepseek-chat", "label": "DeepSeek Chat", "provider": "DeepSeek", "base_url": "https://api.deepseek.com"},
    {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "provider": "DeepSeek", "base_url": "https://api.deepseek.com"},
    {"id": "doubao-seed-2-0-pro-260215", "label": "Doubao Seed 2.0 Pro", "provider": "Volcengine Ark", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    {"id": "doubao-1-5-pro-32k-250115", "label": "Doubao 1.5 Pro 32K", "provider": "Volcengine Ark", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    {"id": "doubao-1-5-lite-32k-250115", "label": "Doubao 1.5 Lite 32K", "provider": "Volcengine Ark", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
]
FALLBACK_AVAILABILITY = {
    "deepseek-chat": True,
    "deepseek-reasoner": True,
    "doubao-seed-2-0-pro-260215": True,
    "doubao-1-5-pro-32k-250115": False,
    "doubao-1-5-lite-32k-250115": False,
}
INTERVENTIONS = {
    "diverge": "请只做发散探索：最多给三个方向，不展开完整方案。",
    "critique": "请进入挑刺模式：只指出问题、风险、约束冲突和证据缺口。",
    "converge": "请进入收敛模式：明确保留、砍掉、延后，并给最小方案。",
    "execute": "请只输出执行任务：文件、接口、UI、验收。",
}
SESSION_DIR = Path("sessions")
WORKSPACE_DIR = Path("workspaces")
WORKSPACE_DOCS_DIR = WORKSPACE_DIR / "docs"
FRONTEND_DIST = Path("frontend/dist")
SKILL_REGISTRY = SkillRegistry()
DOC_TEXT_LIMIT = 12000
DOC_PROMPT_LIMIT = 2400
DOC_PROMPT_TOTAL_LIMIT = 8000


class AgentSettingsPayload(BaseModel):
    enabled: bool = True
    model: str = ""
    skill_id: str = ""
    prompt: str = ""


class TaskBriefPayload(BaseModel):
    objective: str = ""
    background: str = ""
    task_type: str = "general"
    budget_limit: str = ""
    time_limit: str = ""
    existing_assets: str = ""
    constraints: str = ""
    success_metric: str = ""
    failure_criteria: str = ""
    expected_output: str = ""


class DecisionMemoryPayload(BaseModel):
    round_summary: str = ""
    decisions: list[str] = Field(default_factory=list)
    rejected_options: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    active_constraints: list[str] = Field(default_factory=list)
    updated_at: str = ""


class RuntimeConfigPayload(BaseModel):
    project_name: str = "未命名议题"
    preset_prompt: str = ""
    global_constraint: str = ""
    constraint_prompt: str = ""
    judge_rubric: str = DEFAULT_JUDGE_PROMPT
    project_prompt: str = ""
    judge_prompt: str = ""
    output_protocol_prompt: str = ""
    workspace_id: str = ""
    workspace_name: str = ""
    deepseek_api_key: str = ""
    ark_api_key: str = ""
    summary_model: str = ""
    team_name: str = "mvp_hacker_team"
    task_brief: TaskBriefPayload = Field(default_factory=TaskBriefPayload)
    selected_documents: list[str] = Field(default_factory=list)
    selected_documents_context: str = ""
    compact_context: str = ""
    auto_mode: bool = True
    auto_compress_enabled: bool = True
    auto_compress_turn_threshold: int = 6
    auto_compress_char_threshold: int = 20000
    keep_recent_turns: int = 3
    round_mode: RoundMode = "auto"
    enable_judge: bool = True
    summary_enabled: bool = True
    decision_memory: DecisionMemoryPayload = Field(default_factory=DecisionMemoryPayload)
    agents: dict[str, AgentSettingsPayload]
    uploaded_docs: list[dict[str, str]] = Field(default_factory=list)


class RoundRequest(BaseModel):
    user_input: str
    config: RuntimeConfigPayload
    mode: Literal["manual", "auto"] = "manual"


class ContinueRoundRequest(BaseModel):
    mode: Literal["manual", "auto"] = "manual"


class SaveSessionRequest(BaseModel):
    save_name: str


class LoadSessionRequest(BaseModel):
    file_name: str


class WorkspaceUpdatePayload(BaseModel):
    workspace_name: str = "未命名工作区"
    task_brief: TaskBriefPayload = Field(default_factory=TaskBriefPayload)
    global_constraint: str = ""
    constraint_prompt: str = ""
    judge_rubric: str = DEFAULT_JUDGE_PROMPT
    project_prompt: str = ""
    preset_prompt: str = ""
    judge_prompt: str = ""
    output_protocol_prompt: str = ""
    selected_team: str = ""
    selected_skills: dict[str, str] = Field(default_factory=dict)
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    selected_documents: list[str] = Field(default_factory=list)
    compact_context: str = ""
    auto_mode: bool = True
    auto_compress_enabled: bool = True
    auto_compress_turn_threshold: int = 6
    auto_compress_char_threshold: int = 20000
    keep_recent_turns: int = 3
    round_mode: RoundMode = "auto"
    enable_judge: bool = True
    summary_enabled: bool = True
    decision_memory: DecisionMemoryPayload = Field(default_factory=DecisionMemoryPayload)


class WorkspaceCreatePayload(WorkspaceUpdatePayload):
    workspace_id: str = ""


class WorkspaceDocumentCreatePayload(BaseModel):
    name: str
    content: str = ""


class WorkspaceDocumentUpdatePayload(BaseModel):
    name: str | None = None
    content: str


@dataclass
class SessionState:
    session_id: str
    project_name: str = "未命名议题"
    workspace_id: str = ""
    workspace_name: str = ""
    rounds: list[dict[str, Any]] = field(default_factory=list)
    graph_state: dict[str, Any] = field(default_factory=lambda: {"messages": [], "summary": "", "compact_context": "", "decision_memory": {}})
    pending_execution: dict[str, Any] | None = None
    runtime_config: dict[str, Any] = field(default_factory=dict)


class SessionSnapshot(BaseModel):
    session_id: str
    project_name: str
    workspace_id: str = ""
    workspace_name: str = ""
    rounds: list[dict[str, Any]]
    summary: str
    compact_context: str = ""
    decision_memory: DecisionMemoryPayload = Field(default_factory=DecisionMemoryPayload)
    runtime_config: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="Decision Council API", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, SessionState] = {}


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _sanitize_slug(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return normalized[:80] or fallback


def _default_task_brief() -> dict[str, str]:
    return TaskBriefPayload().model_dump()


def _default_decision_memory() -> DecisionMemory:
    return DecisionMemoryPayload().model_dump()


def _normalize_text_value(value: str) -> str:
    normalized = str(value or "").strip()
    normalized = normalized.replace("**", "")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[。．.!！?？]+$", "", normalized)
    return normalized.strip(" -\t")


def _dedupe_text_list(items: list[str], limit: int | None = None) -> list[str]:
    seen: list[str] = []
    for raw in items:
        item = _normalize_text_value(raw)
        if not item or item in seen:
            continue
        seen.append(item)
        if limit is not None and len(seen) >= limit:
            break
    return seen


def _normalize_task_brief(payload: dict[str, Any] | TaskBriefPayload | None) -> dict[str, str]:
    if isinstance(payload, TaskBriefPayload):
        return payload.model_dump()
    return TaskBriefPayload.model_validate(payload or {}).model_dump()


def _normalize_decision_memory(payload: dict[str, Any] | DecisionMemoryPayload | None) -> DecisionMemory:
    if isinstance(payload, DecisionMemoryPayload):
        data = payload.model_dump()
    else:
        data = DecisionMemoryPayload.model_validate(payload or {}).model_dump()
    data["decisions"] = _dedupe_text_list(list(data.get("decisions", [])))
    data["rejected_options"] = _dedupe_text_list(list(data.get("rejected_options", [])))
    data["open_questions"] = _dedupe_text_list(list(data.get("open_questions", [])), limit=8)
    data["next_actions"] = _dedupe_text_list(list(data.get("next_actions", [])), limit=6)
    data["active_constraints"] = _dedupe_text_list(list(data.get("active_constraints", [])), limit=8)
    return data


def _empty_workspace_payload(workspace_id: str, workspace_name: str) -> dict[str, Any]:
    now = _now_iso()
    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "task_brief": _default_task_brief(),
        "global_constraint": "",
        "constraint_prompt": "",
        "judge_rubric": DEFAULT_JUDGE_PROMPT,
        "project_prompt": "",
        "preset_prompt": "",
        "judge_prompt": DEFAULT_JUDGE_PROMPT,
        "output_protocol_prompt": "",
        "selected_team": SKILL_REGISTRY.default_team(),
        "selected_skills": {},
        "prompt_overrides": {},
        "selected_documents": [],
        "compact_context": "",
        "auto_mode": True,
        "auto_compress_enabled": True,
        "auto_compress_turn_threshold": 6,
        "auto_compress_char_threshold": 20000,
        "keep_recent_turns": 3,
        "round_mode": "auto",
        "enable_judge": True,
        "summary_enabled": True,
        "decision_memory": _default_decision_memory(),
        "created_at": now,
        "updated_at": now,
    }


def _workspace_path(workspace_id: str) -> Path:
    safe_id = _sanitize_slug(workspace_id, "workspace")
    return WORKSPACE_DIR / f"{safe_id}.json"


def _workspace_docs_dir(workspace_id: str) -> Path:
    return WORKSPACE_DOCS_DIR / _sanitize_slug(workspace_id, "workspace")


def _doc_file_name(doc_id: str, doc_name: str) -> str:
    safe_doc_id = _sanitize_slug(doc_id, "doc")
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", Path(doc_name).stem).strip(" ._") or "document"
    suffix = Path(doc_name).suffix.lower()
    if suffix not in {".md", ".txt", ".json"}:
        suffix = ".md"
    return f"{safe_doc_id}__{safe_name}{suffix}"


def _parse_doc_file_name(path: Path) -> dict[str, str]:
    stem = path.stem
    if "__" in stem:
        doc_id, safe_name = stem.split("__", 1)
    else:
        doc_id, safe_name = stem, stem
    return {"doc_id": doc_id, "name": f"{safe_name}{path.suffix}"}


def _find_doc_path(workspace_id: str, doc_id: str) -> Path:
    docs_dir = _workspace_docs_dir(workspace_id)
    safe_doc_id = _sanitize_slug(doc_id, "doc")
    for path in docs_dir.glob(f"{safe_doc_id}__*"):
        if path.is_file():
            return path
    raise HTTPException(status_code=404, detail="文档不存在。")


def _ensure_workspace_dirs() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _load_workspace(workspace_id: str) -> dict[str, Any]:
    path = _workspace_path(workspace_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    legacy_missing_auto_fields = "auto_mode" not in payload and "compact_context" not in payload
    base = _empty_workspace_payload(payload.get("workspace_id", workspace_id), payload.get("workspace_name", "未命名工作区"))
    base.update(payload)
    base["task_brief"] = _normalize_task_brief(base.get("task_brief"))
    base["decision_memory"] = _normalize_decision_memory(base.get("decision_memory"))
    base["global_constraint"] = str(base.get("global_constraint") or base.get("constraint_prompt") or "")
    base["judge_rubric"] = str(base.get("judge_rubric") or base.get("judge_prompt") or DEFAULT_JUDGE_PROMPT)
    base["compact_context"] = str(base.get("compact_context") or base.get("summary") or "")
    base["auto_mode"] = bool(base.get("auto_mode", True))
    base["auto_compress_enabled"] = bool(base.get("auto_compress_enabled", True))
    base["auto_compress_turn_threshold"] = int(base.get("auto_compress_turn_threshold", 6) or 6)
    base["auto_compress_char_threshold"] = int(base.get("auto_compress_char_threshold", 20000) or 20000)
    base["keep_recent_turns"] = int(base.get("keep_recent_turns", 3) or 3)
    base["summary_enabled"] = bool(base.get("summary_enabled", True))
    if legacy_missing_auto_fields and base.get("round_mode") == "converge":
      base["round_mode"] = "auto"
    base["selected_documents"] = [str(item) for item in base.get("selected_documents", [])]
    base["selected_skills"] = {key: str(value) for key, value in (base.get("selected_skills") or {}).items()}
    base["prompt_overrides"] = {key: str(value) for key, value in (base.get("prompt_overrides") or {}).items()}
    return base


def _save_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_workspace_dirs()
    workspace_id = _sanitize_slug(payload.get("workspace_id", ""), "workspace")
    existing = None
    path = _workspace_path(workspace_id)
    if path.exists():
        existing = _load_workspace(workspace_id)
    now = _now_iso()
    base = existing or _empty_workspace_payload(workspace_id, payload.get("workspace_name", "未命名工作区"))
    base.update(payload)
    base["workspace_id"] = workspace_id
    base["workspace_name"] = (base.get("workspace_name") or "未命名工作区").strip() or "未命名工作区"
    base["task_brief"] = _normalize_task_brief(base.get("task_brief"))
    base["decision_memory"] = _normalize_decision_memory(base.get("decision_memory"))
    base["created_at"] = existing.get("created_at", now) if existing else now
    base["updated_at"] = now
    path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    _workspace_docs_dir(workspace_id).mkdir(parents=True, exist_ok=True)
    return base


def _list_workspaces() -> list[dict[str, Any]]:
    _ensure_workspace_dirs()
    items = []
    for path in sorted(WORKSPACE_DIR.glob("*.json")):
        payload = _load_workspace(path.stem)
        items.append(
            {
                "workspace_id": payload["workspace_id"],
                "workspace_name": payload["workspace_name"],
                "round_mode": payload.get("round_mode", "converge"),
                "enable_judge": bool(payload.get("enable_judge", True)),
                "selected_team": payload.get("selected_team", ""),
                "updated_at": payload.get("updated_at", ""),
            }
        )
    return items


def _ensure_default_workspace() -> dict[str, Any]:
    items = _list_workspaces()
    if items:
        return _load_workspace(items[0]["workspace_id"])
    workspace = _empty_workspace_payload("default", "默认工作区")
    return _save_workspace(workspace)


def _workspace_documents(workspace_id: str) -> list[dict[str, Any]]:
    _load_workspace(workspace_id)
    docs_dir = _workspace_docs_dir(workspace_id)
    docs_dir.mkdir(parents=True, exist_ok=True)
    selected = set(_load_workspace(workspace_id).get("selected_documents", []))
    items = []
    for path in sorted(docs_dir.iterdir()):
        if not path.is_file():
            continue
        meta = _parse_doc_file_name(path)
        items.append(
            {
                "doc_id": meta["doc_id"],
                "name": meta["name"],
                "selected": meta["doc_id"] in selected,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "size": path.stat().st_size,
            }
        )
    return items


def _doc_excerpt(text: str, limit: int = DOC_PROMPT_LIMIT) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "\n...[内容已截断]"


def _build_selected_documents_context(workspace_id: str, selected_documents: list[str], uploaded_docs: list[dict[str, str]] | None = None) -> str:
    blocks: list[str] = []
    total = 0
    for doc_id in selected_documents:
        try:
            path = _find_doc_path(workspace_id, doc_id)
        except HTTPException:
            continue
        meta = _parse_doc_file_name(path)
        content = path.read_text(encoding="utf-8")
        excerpt = _doc_excerpt(content)
        total += len(excerpt)
        if total > DOC_PROMPT_TOTAL_LIMIT:
            remaining = DOC_PROMPT_TOTAL_LIMIT - (total - len(excerpt))
            if remaining <= 0:
                break
            excerpt = _doc_excerpt(content, remaining)
            total = DOC_PROMPT_TOTAL_LIMIT
        blocks.append(f"文档：{meta['name']}\n内容摘录：\n{excerpt}")
        if total >= DOC_PROMPT_TOTAL_LIMIT:
            break
    if not blocks and uploaded_docs:
        for doc in uploaded_docs[:3]:
            name = str(doc.get("name", "document"))
            excerpt = _doc_excerpt(str(doc.get("content", "")))
            if excerpt:
                blocks.append(f"文档：{name}\n内容摘录：\n{excerpt}")
    return "\n\n".join(blocks)


def _count_message_chars(messages: list[Any]) -> int:
    total = 0
    for message in messages:
        total += len(str(getattr(message, "content", "")))
    return total


def _detect_round_mode(user_input: str, current_mode: str, auto_mode: bool, decision_memory: dict[str, Any], continuing: bool = False) -> str:
    if not auto_mode and current_mode:
        return current_mode
    lowered = user_input.lower()
    if any(token in user_input for token in ("挑刺", "风险", "审查", "有什么问题", "反驳")):
        return "critique"
    if any(token in user_input for token in ("发散", "多几个方向", "备选方案")):
        return "diverge"
    if any(token in user_input for token in ("给 Codex", "开发提示词", "执行", "改哪些文件", "实现")):
        return "execute"
    if any(token in user_input for token in ("收敛", "最终方案", "最小方案")):
        return "converge"
    if continuing and decision_memory.get("decisions"):
        return "execute" if decision_memory.get("next_actions") else "converge"
    if decision_memory.get("decisions"):
        return "converge"
    return "converge"


async def _compress_state_if_needed(
    session: SessionState,
    state: dict[str, Any],
    payload: RuntimeConfigPayload,
    force: bool = False,
) -> dict[str, Any]:
    messages = state.get("messages", [])
    turns = len(session.rounds) + 1
    chars = _count_message_chars(messages)
    should_compress = force
    if payload.auto_compress_enabled:
        should_compress = should_compress or turns >= payload.auto_compress_turn_threshold or chars >= payload.auto_compress_char_threshold
    if not should_compress:
        return {"compressed": False, "chars": chars, "compact_context": state.get("compact_context", "")}
    summary_update = await node_summarizer(state)
    state["summary"] = summary_update.get("summary", "").strip()
    state["compact_context"] = summary_update.get("compact_context", state["summary"]).strip()
    removable_ids = {item.id for item in summary_update.get("messages", []) if isinstance(item, RemoveMessage) and item.id}
    if removable_ids:
        state["messages"] = [message for message in messages if getattr(message, "id", None) not in removable_ids]
    return {"compressed": True, "chars": len(state.get("compact_context", "")), "compact_context": state.get("compact_context", "")}


def _infer_availability(deepseek_key: str, ark_key: str) -> dict[str, bool]:
    return {
        "deepseek-chat": bool(deepseek_key),
        "deepseek-reasoner": bool(deepseek_key),
        "doubao-seed-2-0-pro-260215": bool(ark_key),
        "doubao-1-5-pro-32k-250115": bool(ark_key),
        "doubao-1-5-lite-32k-250115": bool(ark_key),
    }


def _default_model_for_provider(provider: str, availability: dict[str, bool]) -> str:
    for model in MODEL_REGISTRY:
        if model["provider"] == provider and availability.get(model["id"], False):
            return model["id"]
    return ""


def _required_provider_name(model_id: str) -> str:
    return "DeepSeek API Key" if model_id.startswith("deepseek") else "Ark API Key"


def _assert_model_key(model_id: str, api_key: str) -> None:
    if not api_key:
        raise HTTPException(status_code=400, detail=f"模型 `{model_id}` 需要对应的 {_required_provider_name(model_id)}，当前未提供。")


def _registry_for_team(team_name: str | None = None) -> SkillRegistry:
    registry = SkillRegistry(team_name=team_name)
    registry.reload()
    return registry


def _settings_defaults(team_name: str | None = None) -> dict[str, Any]:
    registry = _registry_for_team(team_name)
    settings = load_settings()
    deepseek_key = (
        os.getenv("SHARED_DEEPSEEK_API_KEY", "").strip()
        or (settings.shared_api_key if settings.shared_api_key.startswith("sk-") else "")
        or (settings.agent_a_api_key if settings.agent_a_api_key.startswith("sk-") else "")
    )
    ark_key = (
        os.getenv("ARK_API_KEY", "").strip()
        or (settings.shared_api_key if settings.shared_api_key.startswith("ark-") else "")
        or (settings.agent_a_api_key if settings.agent_a_api_key.startswith("ark-") else "")
    )
    availability = _infer_availability(deepseek_key, ark_key)
    default_team = team_name or registry.default_team()
    summary_default = _default_model_for_provider("DeepSeek", availability) or settings.summary_model
    return {
        "project_name": "默认工作区",
        "preset_prompt": "",
        "global_constraint": "",
        "constraint_prompt": "",
        "judge_rubric": DEFAULT_JUDGE_PROMPT,
        "project_prompt": "",
        "judge_prompt": DEFAULT_JUDGE_PROMPT,
        "output_protocol_prompt": "",
        "workspace_id": "",
        "workspace_name": "",
        "deepseek_api_key": deepseek_key,
        "ark_api_key": ark_key,
        "summary_model": summary_default,
        "team_name": default_team,
        "task_brief": _default_task_brief(),
        "selected_documents": [],
        "selected_documents_context": "",
        "compact_context": "",
        "auto_mode": True,
        "auto_compress_enabled": True,
        "auto_compress_turn_threshold": 6,
        "auto_compress_char_threshold": 20000,
        "keep_recent_turns": 3,
        "round_mode": "auto",
        "enable_judge": True,
        "summary_enabled": True,
        "decision_memory": _default_decision_memory(),
        "agents": {
            "S": {"enabled": True, "model": settings.agent_s_model, "skill_id": (registry.latest_for_agent("S").skill_id if registry.latest_for_agent("S") else ""), "prompt": ""},
            "A": {"enabled": True, "model": settings.agent_a_model, "skill_id": (registry.latest_for_agent("A").skill_id if registry.latest_for_agent("A") else ""), "prompt": ""},
            "B": {"enabled": True, "model": settings.agent_b_model, "skill_id": (registry.latest_for_agent("B").skill_id if registry.latest_for_agent("B") else ""), "prompt": ""},
            "C": {"enabled": True, "model": settings.agent_c_model, "skill_id": (registry.latest_for_agent("C").skill_id if registry.latest_for_agent("C") else ""), "prompt": ""},
        },
        "uploaded_docs": [],
    }


def _empty_session(project_name: str = "未命名议题", workspace: dict[str, Any] | None = None) -> SessionState:
    session_id = uuid4().hex
    session = SessionState(
        session_id=session_id,
        project_name=project_name,
        workspace_id=(workspace or {}).get("workspace_id", ""),
        workspace_name=(workspace or {}).get("workspace_name", ""),
    )
    _sessions[session_id] = session
    return session


def _session_to_snapshot(session: SessionState) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session.session_id,
        project_name=session.project_name,
        workspace_id=session.workspace_id,
        workspace_name=session.workspace_name,
        rounds=session.rounds,
        summary=session.graph_state.get("summary", ""),
        compact_context=session.graph_state.get("compact_context", ""),
        decision_memory=_normalize_decision_memory(session.graph_state.get("decision_memory")),
        runtime_config=session.runtime_config,
    )


def _model_by_id(model_id: str) -> dict[str, str]:
    for model in MODEL_REGISTRY:
        if model["id"] == model_id:
            return model
    raise HTTPException(status_code=400, detail=f"未知模型: {model_id}")


def _model_label(model_id: str) -> str:
    if not model_id:
        return "未配置模型"
    model = _model_by_id(model_id)
    return f"{model['label']} · {model['provider']}"


def _model_options(availability: dict[str, bool]) -> list[dict[str, str]]:
    return [model for model in MODEL_REGISTRY if availability.get(model["id"], False)]


def _select_api_key(model_id: str, deepseek_key: str, ark_key: str) -> str:
    return deepseek_key if model_id.startswith("deepseek") else ark_key


def _read_uploaded_file(uploaded_file: UploadFile, raw: bytes) -> str:
    suffix = uploaded_file.filename.lower().rsplit(".", 1)[-1] if "." in uploaded_file.filename else ""
    if suffix in {"txt", "md", "py", "json", "yaml", "yml"}:
        return raw.decode("utf-8", errors="ignore")
    if suffix == "csv":
        text = raw.decode("utf-8", errors="ignore")
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join([", ".join(row) for row in rows[:200]])
    if suffix == "pdf":
        if PdfReader is None:
            raise HTTPException(status_code=400, detail="未安装 pypdf，当前无法解析 PDF。")
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    if suffix == "docx":
        if Document is None:
            raise HTTPException(status_code=400, detail="未安装 python-docx，当前无法解析 DOCX。")
        document = Document(io.BytesIO(raw))
        return "\n".join(paragraph.text for paragraph in document.paragraphs[:400])
    return raw.decode("utf-8", errors="ignore")


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _compact_error_message(error: Exception) -> str:
    text = str(error).strip()
    lowered = text.lower()
    if "401" in text and ("api key" in lowered or "authentication" in lowered or "unauthorized" in lowered):
        return "API 密钥无效或已失效，请检查当前模型对应的 Key。"
    if "api key" in lowered and ("doesn't exist" in lowered or "invalid" in lowered):
        return "API 密钥无效或不存在，请更新后重试。"
    return text.split("\n", 1)[0]


async def _probe_models_async(deepseek_key: str, ark_key: str) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for model in MODEL_REGISTRY:
        api_key = deepseek_key if model["provider"] == "DeepSeek" else ark_key
        if not api_key:
            results[model["id"]] = False
            continue
        try:
            client = OpenAI(api_key=api_key, base_url=model["base_url"])
            client.chat.completions.create(model=model["id"], messages=[{"role": "user", "content": "只回复OK"}], max_tokens=8)
            results[model["id"]] = True
        except Exception:
            results[model["id"]] = False
    if (deepseek_key or ark_key) and not any(results.values()):
        return FALLBACK_AVAILABILITY.copy()
    return results


def _workspace_for_config(payload: RuntimeConfigPayload) -> dict[str, Any]:
    if payload.workspace_id.strip():
        try:
            workspace = _load_workspace(payload.workspace_id.strip())
        except HTTPException:
            workspace = _save_workspace(
                {
                    "workspace_id": payload.workspace_id.strip(),
                    "workspace_name": payload.workspace_name.strip() or payload.project_name.strip() or "未命名工作区",
                }
            )
    else:
        workspace = _ensure_default_workspace()
    return workspace


def _build_runtime_context(session: SessionState, payload: RuntimeConfigPayload, user_input: str) -> tuple[dict[str, Any], dict[str, Any]]:
    active_agents = [agent_id for agent_id, value in payload.agents.items() if value.enabled]
    if not active_agents:
        raise HTTPException(status_code=400, detail="至少启用一个 Agent，当前轮次才能发送。")

    workspace = _workspace_for_config(payload)
    workspace_payload = _save_workspace(
        {
            **workspace,
            "workspace_name": payload.workspace_name.strip() or workspace["workspace_name"],
            "task_brief": payload.task_brief.model_dump(),
            "global_constraint": payload.global_constraint or payload.constraint_prompt,
            "constraint_prompt": payload.constraint_prompt,
            "judge_rubric": payload.judge_rubric or payload.judge_prompt or workspace.get("judge_rubric", DEFAULT_JUDGE_PROMPT),
            "project_prompt": payload.project_prompt,
            "preset_prompt": payload.preset_prompt,
            "judge_prompt": payload.judge_prompt or workspace.get("judge_prompt", DEFAULT_JUDGE_PROMPT),
            "output_protocol_prompt": payload.output_protocol_prompt,
            "selected_team": payload.team_name,
            "selected_skills": {key: value.skill_id for key, value in payload.agents.items()},
            "prompt_overrides": {key: value.prompt for key, value in payload.agents.items()},
            "selected_documents": payload.selected_documents,
            "compact_context": payload.compact_context or session.graph_state.get("compact_context", ""),
            "auto_mode": payload.auto_mode,
            "auto_compress_enabled": payload.auto_compress_enabled,
            "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
            "auto_compress_char_threshold": payload.auto_compress_char_threshold,
            "keep_recent_turns": payload.keep_recent_turns,
            "round_mode": payload.round_mode,
            "enable_judge": payload.enable_judge,
            "summary_enabled": payload.summary_enabled,
            "decision_memory": payload.decision_memory.model_dump(),
        }
    )

    session.project_name = payload.project_name.strip() or workspace_payload["workspace_name"]
    session.workspace_id = workspace_payload["workspace_id"]
    session.workspace_name = workspace_payload["workspace_name"]

    agent_s_model = payload.agents["S"].model
    agent_a_model = payload.agents["A"].model
    agent_b_model = payload.agents["B"].model
    agent_c_model = payload.agents["C"].model
    summary_model = payload.summary_model or agent_s_model
    agent_s_api_key = _select_api_key(agent_s_model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip())
    agent_a_api_key = _select_api_key(agent_a_model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip())
    agent_b_api_key = _select_api_key(agent_b_model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip())
    agent_c_api_key = _select_api_key(agent_c_model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip())
    summary_api_key = _select_api_key(summary_model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip())

    _assert_model_key(agent_s_model, agent_s_api_key)
    _assert_model_key(agent_a_model, agent_a_api_key)
    _assert_model_key(agent_b_model, agent_b_api_key)
    _assert_model_key(agent_c_model, agent_c_api_key)
    _assert_model_key(summary_model, summary_api_key)

    settings = load_settings(
        agent_s_base_url=_model_by_id(agent_s_model)["base_url"],
        agent_a_base_url=_model_by_id(agent_a_model)["base_url"],
        agent_b_base_url=_model_by_id(agent_b_model)["base_url"],
        agent_c_base_url=_model_by_id(agent_c_model)["base_url"],
        summary_base_url=_model_by_id(summary_model)["base_url"],
        agent_s_model=agent_s_model,
        agent_a_model=agent_a_model,
        agent_b_model=agent_b_model,
        agent_c_model=agent_c_model,
        summary_model=summary_model,
        agent_s_api_key=agent_s_api_key,
        agent_a_api_key=agent_a_api_key,
        agent_b_api_key=agent_b_api_key,
        agent_c_api_key=agent_c_api_key,
        summary_api_key=summary_api_key,
    )
    selected_skills = {key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")}
    prompt_overrides = {key: payload.agents[key].prompt for key in ("S", "A", "B", "C")}
    configure_agents(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills=selected_skills,
        prompt_overrides=prompt_overrides,
        judge_prompt=payload.judge_prompt or workspace_payload.get("judge_prompt", DEFAULT_JUDGE_PROMPT),
        output_protocol_prompt=payload.output_protocol_prompt,
    )

    selected_documents_context = payload.selected_documents_context.strip() or _build_selected_documents_context(
        workspace_payload["workspace_id"], payload.selected_documents, payload.uploaded_docs
    )
    effective_round_mode = _detect_round_mode(
        user_input,
        payload.round_mode,
        payload.auto_mode,
        payload.decision_memory.model_dump(),
        continuing=False,
    )
    graph_messages = messages_from_dict(session.graph_state.get("messages", []))
    history_input = user_input
    state = {
        "messages": graph_messages + [HumanMessage(content=history_input, name="control_center", id=f"user-{uuid4().hex}")],
        "summary": session.graph_state.get("summary", ""),
        "compact_context": payload.compact_context.strip() or session.graph_state.get("compact_context", ""),
        "human_input": user_input,
        "active_agents": active_agents,
        "workspace_id": workspace_payload["workspace_id"],
        "workspace_name": workspace_payload["workspace_name"],
        "preset_prompt": payload.preset_prompt,
        "global_constraint": payload.global_constraint or payload.constraint_prompt,
        "constraint_prompt": payload.constraint_prompt,
        "judge_rubric": payload.judge_rubric or payload.judge_prompt or workspace_payload.get("judge_rubric", DEFAULT_JUDGE_PROMPT),
        "project_prompt": payload.project_prompt,
        "judge_prompt": payload.judge_prompt or workspace_payload.get("judge_prompt", DEFAULT_JUDGE_PROMPT),
        "output_protocol_prompt": payload.output_protocol_prompt,
        "task_brief": payload.task_brief.model_dump(),
        "selected_documents": payload.selected_documents,
        "selected_documents_context": selected_documents_context,
        "auto_mode": payload.auto_mode,
        "auto_compress_enabled": payload.auto_compress_enabled,
        "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
        "auto_compress_char_threshold": payload.auto_compress_char_threshold,
        "keep_recent_turns": payload.keep_recent_turns,
        "summary_enabled": payload.summary_enabled,
        "round_mode": effective_round_mode,
        "enable_judge": payload.enable_judge,
        "decision_memory": payload.decision_memory.model_dump(),
    }
    round_record = {
        "human_input": user_input,
        "workspace_id": workspace_payload["workspace_id"],
        "workspace_name": workspace_payload["workspace_name"],
        "round_mode": effective_round_mode,
        "enable_judge": payload.enable_judge,
        "task_brief": payload.task_brief.model_dump(),
        "global_constraint": payload.global_constraint or payload.constraint_prompt,
        "constraint_prompt": payload.constraint_prompt,
        "judge_rubric": payload.judge_rubric or payload.judge_prompt or workspace_payload.get("judge_rubric", DEFAULT_JUDGE_PROMPT),
        "project_prompt": payload.project_prompt,
        "compact_context": state["compact_context"],
        "selected_documents": payload.selected_documents,
        "active_agents": active_agents,
        "active_agent_models": {
            "S": _model_label(agent_s_model),
            "A": _model_label(agent_a_model),
            "B": _model_label(agent_b_model),
            "C": _model_label(agent_c_model),
        },
        "agent_messages": [],
        "judge_message": None,
        "decision_memory": payload.decision_memory.model_dump(),
    }
    session.runtime_config = payload.model_dump()
    pending_execution = {
        "user_input": user_input,
        "payload": payload.model_dump(),
        "state": state,
        "round_record": round_record,
        "next_agent_index": 0,
        "selected_documents_context": selected_documents_context,
    }
    return pending_execution, settings


async def _finalize_round(session: SessionState, state: dict[str, Any], round_record: dict[str, Any], payload: RuntimeConfigPayload) -> None:
    summary_error = ""
    if payload.summary_enabled:
        try:
            await _compress_state_if_needed(session, state, payload, force=False)
        except Exception as exc:
            summary_error = _compact_error_message(exc)

    round_record["summary_error"] = summary_error
    round_record["compact_context"] = state.get("compact_context", "")
    round_record["decision_memory"] = state.get("decision_memory", _default_decision_memory())
    session.rounds.append(round_record)
    session.graph_state = {
        "messages": messages_to_dict(state["messages"]),
        "summary": state.get("summary", ""),
        "compact_context": state.get("compact_context", ""),
        "decision_memory": state.get("decision_memory", _default_decision_memory()),
    }
    session.runtime_config = payload.model_dump()
    session.pending_execution = None
    _save_workspace(
        {
            **_load_workspace(session.workspace_id),
            "workspace_name": session.workspace_name,
            "task_brief": payload.task_brief.model_dump(),
            "global_constraint": payload.global_constraint or payload.constraint_prompt,
            "constraint_prompt": payload.constraint_prompt,
            "judge_rubric": payload.judge_rubric or payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
            "project_prompt": payload.project_prompt,
            "preset_prompt": payload.preset_prompt,
            "compact_context": state.get("compact_context", ""),
            "judge_prompt": payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
            "output_protocol_prompt": payload.output_protocol_prompt,
            "selected_team": payload.team_name,
            "selected_skills": {key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
            "prompt_overrides": {key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
            "selected_documents": payload.selected_documents,
            "round_mode": payload.round_mode,
            "auto_mode": payload.auto_mode,
            "auto_compress_enabled": payload.auto_compress_enabled,
            "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
            "auto_compress_char_threshold": payload.auto_compress_char_threshold,
            "keep_recent_turns": payload.keep_recent_turns,
            "enable_judge": payload.enable_judge,
            "summary_enabled": payload.summary_enabled,
            "decision_memory": state.get("decision_memory", _default_decision_memory()),
        }
    )


def _next_agent_payload(active_agents: list[str], next_index: int) -> dict[str, str] | None:
    if next_index >= len(active_agents):
        return None
    agent_id = active_agents[next_index]
    spec = get_agent_spec(agent_id)
    return {"agent": agent_id, "display_name": spec.display_name}


async def _stream_pending_execution(session: SessionState, mode: Literal["manual", "auto"], emit_start: bool):
    pending = session.pending_execution
    if pending is None:
        yield _sse_event("round_failed", {"detail": "当前没有可继续的轮次。"})
        return

    payload = RuntimeConfigPayload.model_validate(pending["payload"])
    _, settings = _build_runtime_context(session, payload, pending["user_input"])
    configure_agents(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills={key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
        prompt_overrides={key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
        judge_prompt=payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
        output_protocol_prompt=payload.output_protocol_prompt,
    )

    state = pending["state"]
    round_record = pending["round_record"]
    active_agents = round_record["active_agents"]
    next_index = pending["next_agent_index"]
    if not emit_start and payload.auto_mode:
        state["round_mode"] = _detect_round_mode(pending["user_input"], payload.round_mode, True, state.get("decision_memory", {}), continuing=True)
        round_record["round_mode"] = state["round_mode"]

    if emit_start:
        yield _sse_event("round_started", {"round": round_record, "summary": state["summary"], "session_id": session.session_id})
    else:
        next_agent = _next_agent_payload(active_agents, next_index)
        yield _sse_event("round_resumed", {"round": round_record, "next_agent": next_agent, "session_id": session.session_id})

    stop_after = len(active_agents) if mode == "auto" else min(next_index + 1, len(active_agents))

    try:
        for agent_index in range(next_index, stop_after):
            agent_id = active_agents[agent_index]
            spec = get_agent_spec(agent_id)
            yield _sse_event("agent_started", {"agent": agent_id, "display_name": spec.display_name, "model": round_record["active_agent_models"][agent_id]})
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            try:
                async for chunk in stream_agent_reply(agent_id, state):
                    channel = chunk.get("channel", "content")
                    delta = chunk.get("delta", "")
                    if not delta:
                        continue
                    if channel == "reasoning":
                        reasoning_parts.append(delta)
                    else:
                        content_parts.append(delta)
                    yield _sse_event("agent_delta", {"agent": agent_id, "channel": channel, "delta": delta})

                content = "".join(content_parts).strip()
                reasoning = "".join(reasoning_parts).strip()
                state["messages"] = state["messages"] + [build_agent_ai_message(agent_id, content, reasoning)]
                round_record["agent_messages"].append({"agent": agent_id, "content": content, "reasoning": reasoning})
                pending["next_agent_index"] = agent_index + 1
                yield _sse_event("agent_completed", {"agent": agent_id, "content": content, "reasoning": reasoning})
            except Exception as exc:
                detail = _compact_error_message(exc)
                round_record["agent_messages"].append({"agent": agent_id, "content": "", "reasoning": ""})
                session.pending_execution = None
                yield _sse_event("agent_failed", {"agent": agent_id, "detail": detail, "raw_detail": str(exc)})
                yield _sse_event("round_failed", {"detail": detail, "raw_detail": str(exc)})
                return

        if pending["next_agent_index"] < len(active_agents):
            session.pending_execution = pending
            yield _sse_event("round_paused", {"completed_agent": active_agents[pending["next_agent_index"] - 1], "next_agent": _next_agent_payload(active_agents, pending["next_agent_index"])})
            return

        if payload.enable_judge:
            yield _sse_event("judge_started", {"display_name": "Judge · 裁判收敛"})
            try:
                judge_content = await run_judge(state)
                state["messages"] = state["messages"] + [build_judge_ai_message(judge_content)]
                state["judge_output"] = judge_content
                merged_memory = merge_decision_memory(state.get("decision_memory", {}), judge_content, payload.constraint_prompt)
                state["decision_memory"] = merged_memory
                round_record["judge_message"] = {"agent": "JUDGE", "content": judge_content, "reasoning": ""}
                round_record["decision_memory"] = merged_memory
                yield _sse_event("judge_completed", {"content": judge_content, "decision_memory": merged_memory})
            except Exception as exc:
                detail = _compact_error_message(exc)
                round_record["judge_message"] = {"agent": "JUDGE", "content": "", "reasoning": "", "error": detail}
                yield _sse_event("judge_failed", {"detail": detail, "raw_detail": str(exc)})

        summary_error = ""
        if payload.summary_enabled:
            try:
                compress_info = await _compress_state_if_needed(session, state, payload, force=False)
                if compress_info["compressed"]:
                    yield _sse_event("summary_updated", {"summary": state["summary"], "compact_context": state.get("compact_context", ""), "chars": compress_info["chars"]})
            except Exception as exc:
                summary_error = _compact_error_message(exc)
                yield _sse_event("summary_failed", {"detail": summary_error})

        round_record["summary_error"] = summary_error
        round_record["compact_context"] = state.get("compact_context", "")
        round_record["decision_memory"] = state.get("decision_memory", _default_decision_memory())
        session.rounds.append(round_record)
        session.graph_state = {
            "messages": messages_to_dict(state["messages"]),
            "summary": state.get("summary", ""),
            "compact_context": state.get("compact_context", ""),
            "decision_memory": state.get("decision_memory", _default_decision_memory()),
        }
        session.runtime_config = payload.model_dump()
        session.pending_execution = None
        _save_workspace(
            {
                **_load_workspace(session.workspace_id),
                "workspace_name": session.workspace_name,
                "task_brief": payload.task_brief.model_dump(),
                "global_constraint": payload.global_constraint or payload.constraint_prompt,
                "constraint_prompt": payload.constraint_prompt,
                "judge_rubric": payload.judge_rubric or payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
                "project_prompt": payload.project_prompt,
                "preset_prompt": payload.preset_prompt,
                "compact_context": state.get("compact_context", ""),
                "judge_prompt": payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
                "output_protocol_prompt": payload.output_protocol_prompt,
                "selected_team": payload.team_name,
                "selected_skills": {key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
                "prompt_overrides": {key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
                "selected_documents": payload.selected_documents,
                "round_mode": payload.round_mode,
                "auto_mode": payload.auto_mode,
                "auto_compress_enabled": payload.auto_compress_enabled,
                "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
                "auto_compress_char_threshold": payload.auto_compress_char_threshold,
                "keep_recent_turns": payload.keep_recent_turns,
                "enable_judge": payload.enable_judge,
                "summary_enabled": payload.summary_enabled,
                "decision_memory": state.get("decision_memory", _default_decision_memory()),
            }
        )
        yield _sse_event("round_completed", {"round": round_record, "session": _session_to_snapshot(session).model_dump(), "summary_error": summary_error})
    except asyncio.CancelledError:
        raise


async def _run_round(session: SessionState, payload: RuntimeConfigPayload, user_input: str) -> dict[str, Any]:
    if session.pending_execution is not None:
        raise HTTPException(status_code=409, detail="当前有未结束的轮次，请先继续或终止。")

    pending, settings = _build_runtime_context(session, payload, user_input)
    graph = build_graph(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills={key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
        prompt_overrides={key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
        judge_prompt=payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
        output_protocol_prompt=payload.output_protocol_prompt,
    )
    graph_input = pending["state"]
    config = {"configurable": {"thread_id": session.session_id}}
    await graph.ainvoke(graph_input, config=config)
    snapshot = graph.get_state(config)

    raw_messages = snapshot.values.get("messages", [])
    new_agent_messages = []
    judge_message = None
    for message in reversed(raw_messages):
        if not isinstance(message, AIMessage):
            continue
        agent_id = message.additional_kwargs.get("agent_id")
        if agent_id == "JUDGE" and judge_message is None:
            judge_message = {"agent": "JUDGE", "content": str(message.content), "reasoning": ""}
            continue
        if agent_id in pending["round_record"]["active_agents"] and not any(item["agent"] == agent_id for item in new_agent_messages):
            new_agent_messages.append({"agent": agent_id, "content": str(message.content), "reasoning": str(message.additional_kwargs.get("reasoning_content", ""))})
        if len(new_agent_messages) == len(pending["round_record"]["active_agents"]) and (judge_message or not payload.enable_judge):
            break
    new_agent_messages.reverse()

    round_record = pending["round_record"]
    round_record["agent_messages"] = new_agent_messages
    round_record["judge_message"] = judge_message
    if payload.summary_enabled:
        try:
            compress_info = await _compress_state_if_needed(session, snapshot.values, payload, force=False)
            if compress_info["compressed"]:
                snapshot = graph.get_state(config)
        except Exception:
            pass
    round_record["compact_context"] = snapshot.values.get("compact_context", pending["state"].get("compact_context", ""))
    round_record["decision_memory"] = snapshot.values.get("decision_memory", payload.decision_memory.model_dump())
    session.rounds.append(round_record)
    session.graph_state = {
        "messages": messages_to_dict(snapshot.values.get("messages", [])),
        "summary": snapshot.values.get("summary", ""),
        "compact_context": snapshot.values.get("compact_context", pending["state"].get("compact_context", "")),
        "decision_memory": snapshot.values.get("decision_memory", payload.decision_memory.model_dump()),
    }
    session.runtime_config = payload.model_dump()
    _save_workspace(
        {
            **_load_workspace(session.workspace_id),
            "workspace_name": session.workspace_name,
            "task_brief": payload.task_brief.model_dump(),
            "global_constraint": payload.global_constraint or payload.constraint_prompt,
            "constraint_prompt": payload.constraint_prompt,
            "judge_rubric": payload.judge_rubric or payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
            "project_prompt": payload.project_prompt,
            "preset_prompt": payload.preset_prompt,
            "compact_context": snapshot.values.get("compact_context", pending["state"].get("compact_context", "")),
            "judge_prompt": payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
            "output_protocol_prompt": payload.output_protocol_prompt,
            "selected_team": payload.team_name,
            "selected_skills": {key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
            "prompt_overrides": {key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
            "selected_documents": payload.selected_documents,
            "round_mode": payload.round_mode,
            "auto_mode": payload.auto_mode,
            "auto_compress_enabled": payload.auto_compress_enabled,
            "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
            "auto_compress_char_threshold": payload.auto_compress_char_threshold,
            "keep_recent_turns": payload.keep_recent_turns,
            "enable_judge": payload.enable_judge,
            "summary_enabled": payload.summary_enabled,
            "decision_memory": snapshot.values.get("decision_memory", payload.decision_memory.model_dump()),
        }
    )
    return round_record


async def _stream_round(session: SessionState, request: RoundRequest):
    try:
        if session.pending_execution is not None:
            yield _sse_event("round_failed", {"detail": "当前有未结束的轮次，请先继续或终止。"})
            return
        session.pending_execution, _ = _build_runtime_context(session, request.config, request.user_input.strip())
        async for event in _stream_pending_execution(session, request.mode, emit_start=True):
            yield event
    except Exception as exc:
        session.pending_execution = None
        yield _sse_event("round_failed", {"detail": _compact_error_message(exc), "raw_detail": str(exc)})


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bootstrap")
async def bootstrap(team_name: str | None = None) -> dict[str, Any]:
    registry = _registry_for_team(team_name)
    workspace = _ensure_default_workspace()
    session = _empty_session(project_name=workspace["workspace_name"], workspace=workspace)
    active_team = team_name or workspace.get("selected_team") or registry.default_team()
    defaults = _settings_defaults(active_team)
    defaults.update(
        {
            "project_name": workspace["workspace_name"],
            "workspace_id": workspace["workspace_id"],
            "workspace_name": workspace["workspace_name"],
            "preset_prompt": workspace.get("preset_prompt", ""),
            "global_constraint": workspace.get("global_constraint", workspace.get("constraint_prompt", "")),
            "constraint_prompt": workspace.get("constraint_prompt", ""),
            "judge_rubric": workspace.get("judge_rubric", workspace.get("judge_prompt", DEFAULT_JUDGE_PROMPT)),
            "project_prompt": workspace.get("project_prompt", ""),
            "judge_prompt": workspace.get("judge_prompt", DEFAULT_JUDGE_PROMPT),
            "output_protocol_prompt": workspace.get("output_protocol_prompt", ""),
            "team_name": active_team,
            "task_brief": workspace.get("task_brief", _default_task_brief()),
            "selected_documents": workspace.get("selected_documents", []),
            "compact_context": workspace.get("compact_context", ""),
            "auto_mode": workspace.get("auto_mode", True),
            "auto_compress_enabled": workspace.get("auto_compress_enabled", True),
            "auto_compress_turn_threshold": workspace.get("auto_compress_turn_threshold", 6),
            "auto_compress_char_threshold": workspace.get("auto_compress_char_threshold", 20000),
            "keep_recent_turns": workspace.get("keep_recent_turns", 3),
            "round_mode": workspace.get("round_mode", "auto"),
            "enable_judge": workspace.get("enable_judge", True),
            "summary_enabled": workspace.get("summary_enabled", True),
            "decision_memory": workspace.get("decision_memory", _default_decision_memory()),
        }
    )
    for agent_id in ("S", "A", "B", "C"):
        defaults["agents"][agent_id]["skill_id"] = workspace.get("selected_skills", {}).get(agent_id) or defaults["agents"][agent_id]["skill_id"]
        defaults["agents"][agent_id]["prompt"] = workspace.get("prompt_overrides", {}).get(agent_id, "")
    availability = _infer_availability(defaults["deepseek_api_key"], defaults["ark_api_key"])
    return {
        "session": _session_to_snapshot(session).model_dump(),
        "defaults": defaults,
        "models": MODEL_REGISTRY,
        "available_models": _model_options(availability) or MODEL_REGISTRY,
        "availability": availability,
        "interventions": INTERVENTIONS,
        "agent_specs": {agent_id: asdict(spec) for agent_id, spec in AGENT_SPECS.items()},
        "skills": registry.options_payload(),
        "available_teams": registry.available_teams(),
        "active_team": active_team,
        "workspaces": _list_workspaces(),
        "workspace": workspace,
        "documents": _workspace_documents(workspace["workspace_id"]),
    }


@app.post("/api/models/probe")
async def probe_models(payload: dict[str, str]) -> dict[str, Any]:
    availability = await _probe_models_async(payload.get("deepseek_api_key", "").strip(), payload.get("ark_api_key", "").strip())
    return {"availability": availability, "available_models": _model_options(availability)}


@app.post("/api/files/parse")
async def parse_files(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    parsed = []
    for uploaded_file in files:
        raw = await uploaded_file.read()
        content = _read_uploaded_file(uploaded_file, raw).strip()
        if content:
            parsed.append({"name": uploaded_file.filename, "content": content[:DOC_TEXT_LIMIT]})
    return {"files": parsed}


@app.get("/api/workspaces")
def list_workspaces() -> dict[str, Any]:
    return {"workspaces": _list_workspaces()}


@app.post("/api/workspaces")
def create_workspace(payload: WorkspaceCreatePayload) -> dict[str, Any]:
    requested_id = payload.workspace_id.strip() or payload.workspace_name.strip() or uuid4().hex[:8]
    workspace_id = _sanitize_slug(requested_id, uuid4().hex[:8])
    workspace = _save_workspace(
        {
            "workspace_id": workspace_id,
            "workspace_name": payload.workspace_name.strip() or "未命名工作区",
            "task_brief": payload.task_brief.model_dump(),
            "global_constraint": payload.global_constraint or payload.constraint_prompt,
            "constraint_prompt": payload.constraint_prompt,
            "judge_rubric": payload.judge_rubric or payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
            "project_prompt": payload.project_prompt,
            "preset_prompt": payload.preset_prompt,
            "compact_context": payload.compact_context,
            "judge_prompt": payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
            "output_protocol_prompt": payload.output_protocol_prompt,
            "selected_team": payload.selected_team or SKILL_REGISTRY.default_team(),
            "selected_skills": payload.selected_skills,
            "prompt_overrides": payload.prompt_overrides,
            "selected_documents": payload.selected_documents,
            "round_mode": payload.round_mode,
            "auto_mode": payload.auto_mode,
            "auto_compress_enabled": payload.auto_compress_enabled,
            "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
            "auto_compress_char_threshold": payload.auto_compress_char_threshold,
            "keep_recent_turns": payload.keep_recent_turns,
            "enable_judge": payload.enable_judge,
            "summary_enabled": payload.summary_enabled,
            "decision_memory": payload.decision_memory.model_dump(),
        }
    )
    return {"workspace": workspace}


@app.get("/api/workspaces/{workspace_id}")
def get_workspace(workspace_id: str) -> dict[str, Any]:
    return {"workspace": _load_workspace(workspace_id)}


@app.put("/api/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, payload: WorkspaceUpdatePayload) -> dict[str, Any]:
    current = _load_workspace(workspace_id)
    workspace = _save_workspace(
        {
            **current,
            "workspace_name": payload.workspace_name.strip() or current["workspace_name"],
            "task_brief": payload.task_brief.model_dump(),
            "global_constraint": payload.global_constraint or payload.constraint_prompt,
            "constraint_prompt": payload.constraint_prompt,
            "judge_rubric": payload.judge_rubric or payload.judge_prompt or current.get("judge_rubric", DEFAULT_JUDGE_PROMPT),
            "project_prompt": payload.project_prompt,
            "preset_prompt": payload.preset_prompt,
            "compact_context": payload.compact_context,
            "judge_prompt": payload.judge_prompt or current.get("judge_prompt", DEFAULT_JUDGE_PROMPT),
            "output_protocol_prompt": payload.output_protocol_prompt,
            "selected_team": payload.selected_team or current.get("selected_team", ""),
            "selected_skills": payload.selected_skills,
            "prompt_overrides": payload.prompt_overrides,
            "selected_documents": payload.selected_documents,
            "round_mode": payload.round_mode,
            "auto_mode": payload.auto_mode,
            "auto_compress_enabled": payload.auto_compress_enabled,
            "auto_compress_turn_threshold": payload.auto_compress_turn_threshold,
            "auto_compress_char_threshold": payload.auto_compress_char_threshold,
            "keep_recent_turns": payload.keep_recent_turns,
            "enable_judge": payload.enable_judge,
            "summary_enabled": payload.summary_enabled,
            "decision_memory": payload.decision_memory.model_dump(),
        }
    )
    return {"workspace": workspace}


@app.get("/api/workspaces/{workspace_id}/documents")
def list_workspace_documents(workspace_id: str) -> dict[str, Any]:
    return {"documents": _workspace_documents(workspace_id)}


@app.get("/api/workspaces/{workspace_id}/documents/{doc_id}")
def get_workspace_document(workspace_id: str, doc_id: str) -> dict[str, Any]:
    path = _find_doc_path(workspace_id, doc_id)
    meta = _parse_doc_file_name(path)
    return {
        "document": {
            "doc_id": meta["doc_id"],
            "name": meta["name"],
            "content": path.read_text(encoding="utf-8"),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }
    }


@app.put("/api/workspaces/{workspace_id}/documents/{doc_id}")
def update_workspace_document(workspace_id: str, doc_id: str, payload: WorkspaceDocumentUpdatePayload) -> dict[str, Any]:
    _load_workspace(workspace_id)
    current_path = _find_doc_path(workspace_id, doc_id)
    current_meta = _parse_doc_file_name(current_path)
    target_name = payload.name or current_meta["name"]
    target_path = _workspace_docs_dir(workspace_id) / _doc_file_name(doc_id, target_name)
    current_path.unlink(missing_ok=True)
    target_path.write_text(payload.content, encoding="utf-8")
    return {"document": {"doc_id": doc_id, "name": _parse_doc_file_name(target_path)["name"], "content": payload.content}}


@app.post("/api/workspaces/{workspace_id}/documents")
async def create_workspace_document(
    workspace_id: str,
    name: str | None = Form(default=None),
    content: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    _load_workspace(workspace_id)
    if file is not None:
        raw = await file.read()
        parsed_content = _read_uploaded_file(file, raw).strip()
        doc_name = file.filename or "document.md"
        doc_content = parsed_content[:DOC_TEXT_LIMIT]
    else:
        if not name:
            raise HTTPException(status_code=400, detail="缺少文档名称。")
        doc_name = name
        doc_content = (content or "")[:DOC_TEXT_LIMIT]
    doc_id = _sanitize_slug(Path(doc_name).stem, "doc") + "_" + uuid4().hex[:8]
    path = _workspace_docs_dir(workspace_id) / _doc_file_name(doc_id, doc_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc_content, encoding="utf-8")
    return {"document": {"doc_id": doc_id, "name": _parse_doc_file_name(path)["name"], "content": doc_content}}


@app.delete("/api/workspaces/{workspace_id}/documents/{doc_id}")
def delete_workspace_document(workspace_id: str, doc_id: str) -> dict[str, Any]:
    path = _find_doc_path(workspace_id, doc_id)
    path.unlink()
    workspace = _load_workspace(workspace_id)
    workspace["selected_documents"] = [item for item in workspace.get("selected_documents", []) if item != doc_id]
    _save_workspace(workspace)
    return {"deleted": doc_id}


@app.post("/api/sessions")
def create_session(payload: dict[str, str] | None = None) -> dict[str, Any]:
    project_name = (payload or {}).get("project_name", "未命名议题")
    workspace = _ensure_default_workspace()
    session = _empty_session(project_name=project_name, workspace=workspace)
    return {"session": _session_to_snapshot(session).model_dump()}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    return {"session": _session_to_snapshot(session).model_dump()}


@app.get("/api/saved-sessions")
def list_saved_sessions() -> dict[str, Any]:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SESSION_DIR.glob("*.json"), reverse=True)
    return {"files": [path.name for path in files]}


@app.delete("/api/saved-sessions/{file_name}")
def delete_saved_session(file_name: str) -> dict[str, Any]:
    path = SESSION_DIR / Path(file_name).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="存档不存在。")
    path.unlink()
    return {"deleted": path.name}


@app.post("/api/sessions/{session_id}/rounds")
async def create_round(session_id: str, request: RoundRequest) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    round_record = await _run_round(session, request.config, request.user_input.strip())
    return {"round": round_record, "session": _session_to_snapshot(session).model_dump()}


@app.post("/api/sessions/{session_id}/rounds/stream")
async def create_round_stream(session_id: str, request: RoundRequest) -> StreamingResponse:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    return StreamingResponse(_stream_round(session, request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/api/sessions/{session_id}/rounds/continue/stream")
async def continue_round_stream(session_id: str, request: ContinueRoundRequest) -> StreamingResponse:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    if session.pending_execution is None:
        raise HTTPException(status_code=409, detail="当前没有可继续的轮次。")
    return StreamingResponse(_stream_pending_execution(session, request.mode, emit_start=False), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/api/sessions/{session_id}/rounds/terminate")
def terminate_round(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    had_pending = session.pending_execution is not None
    session.pending_execution = None
    return {"terminated": had_pending}


@app.post("/api/sessions/{session_id}/compress")
async def compress_session_context(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    payload_dict = session.runtime_config or _settings_defaults()
    if "agents" not in payload_dict:
        payload_dict["agents"] = _settings_defaults().get("agents", {})
    payload = RuntimeConfigPayload.model_validate(payload_dict)
    _, settings = _build_runtime_context(session, payload, user_input="压缩当前上下文")
    configure_agents(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills={key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
        prompt_overrides={key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
        judge_prompt=payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
        output_protocol_prompt=payload.output_protocol_prompt,
    )
    state = {
        "messages": messages_from_dict(session.graph_state.get("messages", [])),
        "summary": session.graph_state.get("summary", ""),
        "compact_context": session.graph_state.get("compact_context", ""),
        "decision_memory": _normalize_decision_memory(session.graph_state.get("decision_memory")),
        "keep_recent_turns": payload.keep_recent_turns,
    }
    result = await _compress_state_if_needed(session, state, payload, force=True)
    session.graph_state = {
        "messages": messages_to_dict(state["messages"]),
        "summary": state.get("summary", ""),
        "compact_context": state.get("compact_context", ""),
        "decision_memory": state.get("decision_memory", _default_decision_memory()),
    }
    session.runtime_config = {**session.runtime_config, "compact_context": session.graph_state["compact_context"]}
    return {
        "compact_context": session.graph_state["compact_context"],
        "summary": session.graph_state["summary"],
        "chars": result["chars"],
        "decision_memory": session.graph_state["decision_memory"],
    }


@app.post("/api/sessions/{session_id}/export")
def export_session(session_id: str, payload: RuntimeConfigPayload) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    summary_model = payload.summary_model or payload.agents["S"].model
    summary_api_key = _select_api_key(summary_model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip())
    _assert_model_key(summary_model, summary_api_key)
    settings = load_settings(
        summary_base_url=_model_by_id(summary_model)["base_url"],
        summary_model=summary_model,
        summary_api_key=summary_api_key,
        agent_s_api_key=_select_api_key(payload.agents["S"].model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip()),
        agent_a_api_key=_select_api_key(payload.agents["A"].model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip()),
        agent_b_api_key=_select_api_key(payload.agents["B"].model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip()),
        agent_c_api_key=_select_api_key(payload.agents["C"].model, payload.deepseek_api_key.strip(), payload.ark_api_key.strip()),
    )
    configure_agents(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills={key: payload.agents[key].skill_id for key in ("S", "A", "B", "C")},
        prompt_overrides={key: payload.agents[key].prompt for key in ("S", "A", "B", "C")},
        judge_prompt=payload.judge_prompt or DEFAULT_JUDGE_PROMPT,
        output_protocol_prompt=payload.output_protocol_prompt,
    )
    bundle = generate_export_bundle(project_name=session.project_name, summary=session.graph_state.get("summary", ""), messages=messages_from_dict(session.graph_state.get("messages", [])))
    return bundle


@app.post("/api/sessions/{session_id}/save")
def save_session(session_id: str, request: SaveSessionRequest) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = _sanitize_slug(request.save_name, "session")
    path = SESSION_DIR / f"{timestamp}_{safe_name}.json"
    payload = {
        "project_name": session.project_name,
        "workspace_id": session.workspace_id,
        "workspace_name": session.workspace_name,
        "rounds": session.rounds,
        "graph_state": session.graph_state,
        "runtime_config": session.runtime_config,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file_name": path.name}


@app.post("/api/sessions/load")
def load_session(request: LoadSessionRequest) -> dict[str, Any]:
    path = SESSION_DIR / Path(request.file_name).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="存档不存在。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    workspace_id = payload.get("workspace_id", "")
    workspace_name = payload.get("workspace_name", payload.get("project_name", "未命名议题"))
    if workspace_id:
        try:
            _load_workspace(workspace_id)
        except HTTPException:
            _save_workspace({"workspace_id": workspace_id, "workspace_name": workspace_name})
    session = _empty_session(project_name=payload.get("project_name", "未命名议题"))
    session.workspace_id = workspace_id
    session.workspace_name = workspace_name
    session.rounds = payload.get("rounds", [])
    raw_graph_state = payload.get("graph_state", {"messages": [], "summary": ""})
    session.graph_state = {
        "messages": raw_graph_state.get("messages", []),
        "summary": raw_graph_state.get("summary", ""),
        "compact_context": raw_graph_state.get("compact_context", raw_graph_state.get("summary", "")),
        "decision_memory": _normalize_decision_memory(raw_graph_state.get("decision_memory")),
    }
    session.runtime_config = payload.get("runtime_config", {})
    return {"session": _session_to_snapshot(session).model_dump()}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


def main() -> None:
    import uvicorn

    uvicorn.run("backend.api:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
