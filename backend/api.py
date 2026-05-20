from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, messages_from_dict, messages_to_dict
from openai import OpenAI
from pydantic import BaseModel, Field

from agents import (
    AGENT_SPECS,
    build_agent_ai_message,
    configure_agents,
    generate_export_bundle,
    get_agent_spec,
    node_summarizer,
    stream_agent_reply,
)
from graph import build_graph
from hub.config import load_settings
from skill_registry import SkillRegistry

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
    "overdesign": "⚠️ 场外干预：你们陷入了过度设计的自嗨！现在，预算削减 80%，且系统必须在 3 天内上线。抛弃所有重型中间件（如消息队列、图数据库），只用 Python 标准库和 SQLite，给我一个极简的降级替代方案！",
    "common_sense": "⚠️ 场外干预：停止堆砌 AI 概念！针对你们刚才的方案，指出其中【可以用传统非 AI 代码（如正则、普通 SQL、硬编码规则）解决，却错误地引入了 LLM】的地方，并立即修改架构。",
    "catastrophe": "⚠️ 场外干预：红队极端推演！假设最大的外部依赖 API（如豆包 Vision 或 DeepSeek）彻底封禁了我们的 IP。在不购买任何新服务器的前提下，整个业务流如何不中断？给出纯本地的保底方案。",
}
SESSION_DIR = Path("sessions")
FRONTEND_DIST = Path("frontend/dist")
SKILL_REGISTRY = SkillRegistry()


class AgentSettingsPayload(BaseModel):
    enabled: bool = True
    model: str = ""
    skill_id: str = ""
    prompt: str = ""


class RuntimeConfigPayload(BaseModel):
    project_name: str = "未命名议题"
    preset_prompt: str = "优先输出高信息密度结论，避免空泛建议。"
    deepseek_api_key: str = ""
    ark_api_key: str = ""
    summary_model: str = ""
    team_name: str = "mvp_hacker_team"
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


@dataclass
class SessionState:
    session_id: str
    project_name: str = "未命名议题"
    rounds: list[dict[str, Any]] = field(default_factory=list)
    graph_state: dict[str, Any] = field(default_factory=lambda: {"messages": [], "summary": ""})
    pending_execution: dict[str, Any] | None = None


class SessionSnapshot(BaseModel):
    session_id: str
    project_name: str
    rounds: list[dict[str, Any]]
    summary: str


app = FastAPI(title="Decision Council API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, SessionState] = {}


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
        raise HTTPException(
            status_code=400,
            detail=f"模型 `{model_id}` 需要对应的 {_required_provider_name(model_id)}，当前未提供。",
        )


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
    preferred_architect_model = "doubao-seed-2-0-pro-260215"
    agent_s_default = preferred_architect_model if availability.get(preferred_architect_model, False) else (
        settings.agent_s_model if availability.get(settings.agent_s_model, False) else (
            _default_model_for_provider("Volcengine Ark", availability) or _default_model_for_provider("DeepSeek", availability) or settings.agent_s_model
        )
    )
    agent_a_default = _default_model_for_provider("Volcengine Ark", availability) or _default_model_for_provider("DeepSeek", availability) or settings.agent_a_model
    deepseek_default = _default_model_for_provider("DeepSeek", availability) or settings.agent_b_model
    ark_default = _default_model_for_provider("Volcengine Ark", availability) or settings.agent_b_model
    agent_b_default = settings.agent_b_model if availability.get(settings.agent_b_model, False) else deepseek_default or ark_default
    agent_c_default = settings.agent_c_model if availability.get(settings.agent_c_model, False) else deepseek_default or ark_default
    summary_default = _default_model_for_provider("DeepSeek", availability) or agent_a_default or settings.summary_model
    return {
        "project_name": "未命名议题",
        "preset_prompt": "优先输出高信息密度结论，避免空泛建议。",
        "deepseek_api_key": deepseek_key,
        "ark_api_key": ark_key,
        "summary_model": summary_default,
        "team_name": team_name or registry.default_team(),
        "agents": {
            "S": {"enabled": True, "model": agent_s_default, "skill_id": (registry.latest_for_agent("S").skill_id if registry.latest_for_agent("S") else ""), "prompt": ""},
            "A": {"enabled": bool((team_name or registry.default_team()) != "mvp_hacker_team"), "model": agent_a_default, "skill_id": (registry.latest_for_agent("A").skill_id if registry.latest_for_agent("A") else ""), "prompt": ""},
            "B": {"enabled": True, "model": agent_b_default, "skill_id": (registry.latest_for_agent("B").skill_id if registry.latest_for_agent("B") else ""), "prompt": ""},
            "C": {"enabled": True, "model": agent_c_default, "skill_id": (registry.latest_for_agent("C").skill_id if registry.latest_for_agent("C") else ""), "prompt": ""},
        },
    }


def _empty_session(project_name: str = "未命名议题") -> SessionState:
    session_id = uuid4().hex
    session = SessionState(session_id=session_id, project_name=project_name)
    _sessions[session_id] = session
    return session


def _session_to_snapshot(session: SessionState) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session.session_id,
        project_name=session.project_name,
        rounds=session.rounds,
        summary=session.graph_state.get("summary", ""),
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


def _build_context_block(uploaded_docs: list[dict[str, str]]) -> str:
    if not uploaded_docs:
        return ""
    return "\n\n".join(f"文档名: {doc['name']}\n{doc['content']}" for doc in uploaded_docs)


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
            client.chat.completions.create(
                model=model["id"],
                messages=[{"role": "user", "content": "只回复OK"}],
                max_tokens=8,
            )
            results[model["id"]] = True
        except Exception:
            results[model["id"]] = False
    if (deepseek_key or ark_key) and not any(results.values()):
        return FALLBACK_AVAILABILITY.copy()
    return results


def _build_runtime_context(
    session: SessionState,
    payload: RuntimeConfigPayload,
    user_input: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    active_agents = [agent_id for agent_id, value in payload.agents.items() if value.enabled]
    if not active_agents:
        raise HTTPException(status_code=400, detail="至少启用一个 Agent，当前轮次才能发送。")

    session.project_name = payload.project_name.strip() or "未命名议题"
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
    selected_skills = {
        "S": payload.agents["S"].skill_id,
        "A": payload.agents["A"].skill_id,
        "B": payload.agents["B"].skill_id,
        "C": payload.agents["C"].skill_id,
    }
    prompt_overrides = {
        "S": payload.agents["S"].prompt,
        "A": payload.agents["A"].prompt,
        "B": payload.agents["B"].prompt,
        "C": payload.agents["C"].prompt,
    }
    configure_agents(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills=selected_skills,
        prompt_overrides=prompt_overrides,
    )

    context_block = _build_context_block(payload.uploaded_docs)
    history_input = f"[项目:{session.project_name}]\n{user_input}"
    if context_block:
        history_input += f"\n\n[参考资料]\n{context_block}"

    state = {
        "messages": messages_from_dict(session.graph_state.get("messages", []))
        + [HumanMessage(content=history_input, name="control_center", id=f"user-{uuid4().hex}")],
        "summary": session.graph_state.get("summary", ""),
        "human_input": user_input,
        "active_agents": active_agents,
    }
    round_record = {
        "human_input": user_input,
        "active_agents": active_agents,
        "active_agent_models": {
            "S": _model_label(agent_s_model),
            "A": _model_label(agent_a_model),
            "B": _model_label(agent_b_model),
            "C": _model_label(agent_c_model),
        },
        "agent_messages": [],
    }
    pending_execution = {
        "user_input": user_input,
        "payload": payload.model_dump(),
        "state": state,
        "round_record": round_record,
        "next_agent_index": 0,
    }
    return pending_execution, settings


async def _finalize_round(session: SessionState, state: dict[str, Any], round_record: dict[str, Any]) -> None:
    if len(state["messages"]) > 10:
        try:
            summary_update = await node_summarizer(state)
            state["summary"] = summary_update.get("summary", "").strip()
            removable_ids = {
                item.id for item in summary_update.get("messages", []) if isinstance(item, RemoveMessage) and item.id
            }
            if removable_ids:
                state["messages"] = [message for message in state["messages"] if getattr(message, "id", None) not in removable_ids]
        except Exception:
            pass

    session.rounds.append(round_record)
    session.graph_state = {
        "messages": messages_to_dict(state["messages"]),
        "summary": state.get("summary", ""),
    }
    session.pending_execution = None


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
        selected_skills={
            "S": payload.agents["S"].skill_id,
            "A": payload.agents["A"].skill_id,
            "B": payload.agents["B"].skill_id,
            "C": payload.agents["C"].skill_id,
        },
        prompt_overrides={
            "S": payload.agents["S"].prompt,
            "A": payload.agents["A"].prompt,
            "B": payload.agents["B"].prompt,
            "C": payload.agents["C"].prompt,
        },
    )

    state = pending["state"]
    round_record = pending["round_record"]
    active_agents = round_record["active_agents"]
    next_index = pending["next_agent_index"]

    if emit_start:
        yield _sse_event(
            "round_started",
            {"round": round_record, "summary": state["summary"], "session_id": session.session_id},
        )
    else:
        next_agent = _next_agent_payload(active_agents, next_index)
        yield _sse_event(
            "round_resumed",
            {"round": round_record, "next_agent": next_agent, "session_id": session.session_id},
        )

    stop_after = len(active_agents) if mode == "auto" else min(next_index + 1, len(active_agents))

    try:
        for agent_index in range(next_index, stop_after):
            agent_id = active_agents[agent_index]
            spec = get_agent_spec(agent_id)
            yield _sse_event(
                "agent_started",
                {
                    "agent": agent_id,
                    "display_name": spec.display_name,
                    "model": round_record["active_agent_models"][agent_id],
                },
            )
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
                yield _sse_event(
                    "agent_failed",
                    {"agent": agent_id, "detail": detail, "raw_detail": str(exc)},
                )
                yield _sse_event("round_failed", {"detail": detail, "raw_detail": str(exc)})
                return

        if pending["next_agent_index"] < len(active_agents):
            session.pending_execution = pending
            yield _sse_event(
                "round_paused",
                {
                    "completed_agent": active_agents[pending["next_agent_index"] - 1],
                    "next_agent": _next_agent_payload(active_agents, pending["next_agent_index"]),
                },
            )
            return

        summary_error = ""
        if len(state["messages"]) > 10:
            try:
                summary_update = await node_summarizer(state)
                state["summary"] = summary_update.get("summary", "").strip()
                removable_ids = {
                    item.id for item in summary_update.get("messages", []) if isinstance(item, RemoveMessage) and item.id
                }
                if removable_ids:
                    state["messages"] = [message for message in state["messages"] if getattr(message, "id", None) not in removable_ids]
                yield _sse_event("summary_updated", {"summary": state["summary"]})
            except Exception as exc:
                summary_error = _compact_error_message(exc)
                yield _sse_event("summary_failed", {"detail": summary_error})

        session.rounds.append(round_record)
        session.graph_state = {
            "messages": messages_to_dict(state["messages"]),
            "summary": state.get("summary", ""),
        }
        session.pending_execution = None
        yield _sse_event(
            "round_completed",
            {
                "round": round_record,
                "session": _session_to_snapshot(session).model_dump(),
                "summary_error": summary_error,
            },
        )
    except asyncio.CancelledError:
        raise


async def _run_round(session: SessionState, payload: RuntimeConfigPayload, user_input: str) -> dict[str, Any]:
    if session.pending_execution is not None:
        raise HTTPException(status_code=409, detail="当前有未结束的轮次，请先继续或终止。")
    active_agents = [agent_id for agent_id, value in payload.agents.items() if value.enabled]
    if not active_agents:
        raise HTTPException(status_code=400, detail="至少启用一个 Agent，当前轮次才能发送。")

    session.project_name = payload.project_name.strip() or "未命名议题"
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
    configure_agents(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills={
            "S": payload.agents["S"].skill_id,
            "A": payload.agents["A"].skill_id,
            "B": payload.agents["B"].skill_id,
            "C": payload.agents["C"].skill_id,
        },
        prompt_overrides={
            "S": payload.agents["S"].prompt,
            "A": payload.agents["A"].prompt,
            "B": payload.agents["B"].prompt,
            "C": payload.agents["C"].prompt,
        },
    )
    graph = build_graph(
        settings=settings,
        preset_prompt=payload.preset_prompt,
        team_name=payload.team_name,
        selected_skills={
            "S": payload.agents["S"].skill_id,
            "A": payload.agents["A"].skill_id,
            "B": payload.agents["B"].skill_id,
            "C": payload.agents["C"].skill_id,
        },
        prompt_overrides={
            "S": payload.agents["S"].prompt,
            "A": payload.agents["A"].prompt,
            "B": payload.agents["B"].prompt,
            "C": payload.agents["C"].prompt,
        },
    )
    context_block = _build_context_block(payload.uploaded_docs)
    history_input = f"[项目:{session.project_name}]\n{user_input}"
    if context_block:
        history_input += f"\n\n[参考资料]\n{context_block}"

    graph_input = {
        "messages": messages_from_dict(session.graph_state.get("messages", []))
        + [HumanMessage(content=history_input, name="control_center", id=f"user-{uuid4().hex}")],
        "summary": session.graph_state.get("summary", ""),
        "human_input": user_input,
        "active_agents": active_agents,
    }
    config = {"configurable": {"thread_id": session.session_id}}
    await graph.ainvoke(graph_input, config=config)
    snapshot = graph.get_state(config)

    raw_messages = snapshot.values.get("messages", [])
    new_agent_messages = []
    for message in reversed(raw_messages):
        if not isinstance(message, AIMessage):
            continue
        agent_id = message.additional_kwargs.get("agent_id")
        if agent_id in active_agents and not any(item["agent"] == agent_id for item in new_agent_messages):
            new_agent_messages.append(
                {
                    "agent": agent_id,
                    "content": str(message.content),
                    "reasoning": str(message.additional_kwargs.get("reasoning_content", "")),
                }
            )
        if len(new_agent_messages) == len(active_agents):
            break
    new_agent_messages.reverse()

    round_record = {
        "human_input": user_input,
        "active_agents": active_agents,
        "active_agent_models": {
            "S": _model_label(agent_s_model),
            "A": _model_label(agent_a_model),
            "B": _model_label(agent_b_model),
            "C": _model_label(agent_c_model),
        },
        "agent_messages": new_agent_messages,
    }
    session.rounds.append(round_record)
    session.graph_state = {
        "messages": messages_to_dict(snapshot.values.get("messages", [])),
        "summary": snapshot.values.get("summary", ""),
    }
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
    session = _empty_session()
    active_team = team_name or registry.default_team()
    defaults = _settings_defaults(active_team)
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
            parsed.append({"name": uploaded_file.filename, "content": content[:20000]})
    return {"files": parsed}


@app.post("/api/sessions")
def create_session(payload: dict[str, str] | None = None) -> dict[str, Any]:
    project_name = (payload or {}).get("project_name", "未命名议题")
    session = _empty_session(project_name=project_name)
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
    return {
        "round": round_record,
        "session": _session_to_snapshot(session).model_dump(),
    }


@app.post("/api/sessions/{session_id}/rounds/stream")
async def create_round_stream(session_id: str, request: RoundRequest) -> StreamingResponse:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    return StreamingResponse(
        _stream_round(session, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/sessions/{session_id}/rounds/continue/stream")
async def continue_round_stream(session_id: str, request: ContinueRoundRequest) -> StreamingResponse:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    if session.pending_execution is None:
        raise HTTPException(status_code=409, detail="当前没有可继续的轮次。")
    return StreamingResponse(
        _stream_pending_execution(session, request.mode, emit_start=False),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/sessions/{session_id}/rounds/terminate")
def terminate_round(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    had_pending = session.pending_execution is not None
    session.pending_execution = None
    return {"terminated": had_pending}


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
    configure_agents(settings=settings, preset_prompt=payload.preset_prompt, team_name=payload.team_name, prompt_overrides={})
    bundle = generate_export_bundle(
        project_name=session.project_name,
        summary=session.graph_state.get("summary", ""),
        messages=messages_from_dict(session.graph_state.get("messages", [])),
    )
    return bundle


@app.post("/api/sessions/{session_id}/save")
def save_session(session_id: str, request: SaveSessionRequest) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in request.save_name).strip("_") or "session"
    path = SESSION_DIR / f"{timestamp}_{safe_name}.json"
    payload = {
        "project_name": session.project_name,
        "rounds": session.rounds,
        "graph_state": session.graph_state,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file_name": path.name}


@app.post("/api/sessions/load")
def load_session(request: LoadSessionRequest) -> dict[str, Any]:
    path = SESSION_DIR / request.file_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="存档不存在。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    session = _empty_session(project_name=payload.get("project_name", "未命名议题"))
    session.rounds = payload.get("rounds", [])
    session.graph_state = payload.get("graph_state", {"messages": [], "summary": ""})
    return {"session": _session_to_snapshot(session).model_dump()}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


def main() -> None:
    import uvicorn

    uvicorn.run("backend.api:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
