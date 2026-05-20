from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from textwrap import dedent
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_openai import ChatOpenAI

from hub.config import Settings
from skill_registry import SkillRegistry
from state import AgentId, CouncilState, DecisionMemory, RoundMode, TaskBrief


DEFAULT_ACTIVE_AGENTS: list[AgentId] = ["S", "A", "B", "C"]
AGENT_ORDER: tuple[AgentId, ...] = ("S", "A", "B", "C")
JUDGE_NODE_NAME = "judge"
JUDGE_DISPLAY_NAME = "Judge · 裁判收敛"
BASE_SAFETY_PROMPT = dedent(
    """
    你在一个通用多 Agent 决策工作台中工作。
    基础要求：
    1. 不得把未提供的数据说成已证实事实；没有依据时明确写“未知 / 需验证 / 需用户补充”。
    2. 不得把代码里的默认文案当作业务事实；所有业务约束都来自当前协议上下文。
    3. 如果协议上下文、已否决方案、已确认决策与人设冲突，以协议上下文为准。
    4. 优先输出可执行、可验证、可回滚的内容，避免空泛口号。
    """
).strip()
DEFAULT_JUDGE_PROMPT = dedent(
    """
    你是独立 Judge，不是普通 Agent，不负责扩写新大方案。
    你只基于当前工作区的约束、背景、文档、已确认决策、已否决方案和本轮 Agent 输出做审查与收敛。
    你不能根据硬编码业务规则判断；只能依据当前上下文。
    输出必须严格使用以下标题：

    【是否跑偏】
    - 是 / 否
    - 原因：

    【是否违反当前约束】
    - 是 / 否
    - 涉及内容：

    【是否超出当前资源或预算】
    - 是 / 否 / 未提供预算
    - 涉及内容：

    【是否重复已否决方案】
    - 是 / 否
    - 涉及内容：

    【是否存在未证实数字或伪结论】
    - 是 / 否
    - 涉及内容：

    【必须砍掉的内容】
    1.
    2.
    3.

    【保留的最小方案】
    1.
    2.
    3.

    【已确认决策】
    1.
    2.
    3.

    【已否决方案】
    1.
    2.
    3.

    【下一步动作】
    1.
    2.
    3.

    【需要用户补充的信息】
    1.
    2.
    3.

    【下一轮建议提问】
    一句话说明下一轮最该问什么。

    最后追加一个 JSON 代码块，格式如下：
    ```json
    {
      "confirmed_decisions": [],
      "rejected_options": [],
      "next_actions": [],
      "open_questions": [],
      "must_cut": [],
      "minimal_plan": [],
      "needs_user_input": []
    }
    ```
    """
).strip()


@dataclass(frozen=True)
class AgentSpec:
    agent_id: AgentId
    node_name: str
    run_name: str
    display_name: str
    avatar: str
    color: str
    system_prompt: str


AGENT_SPECS: dict[AgentId, AgentSpec] = {
    "S": AgentSpec(
        agent_id="S",
        node_name="agent_s",
        run_name="Agent_S",
        display_name="S·Agent",
        avatar="S",
        color="#4F46E5",
        system_prompt="你是 Agent S，负责提出清晰初稿并整合前文，但具体业务边界完全服从当前协议上下文。",
    ),
    "A": AgentSpec(
        agent_id="A",
        node_name="agent_a",
        run_name="Agent_A",
        display_name="A·Agent",
        avatar="A",
        color="#D97706",
        system_prompt="你是 Agent A，负责补充替代角度与不同路径，但不能脱离当前协议上下文。",
    ),
    "B": AgentSpec(
        agent_id="B",
        node_name="agent_b",
        run_name="Agent_B",
        display_name="B·Agent",
        avatar="B",
        color="#0891B2",
        system_prompt="你是 Agent B，负责实现、结构、执行与验证视角，但不能覆盖用户未提供的业务事实。",
    ),
    "C": AgentSpec(
        agent_id="C",
        node_name="agent_c",
        run_name="Agent_C",
        display_name="C·Agent",
        avatar="C",
        color="#B91C1C",
        system_prompt="你是 Agent C，负责批判、风险与边界审查，但仍必须服从当前协议上下文与阶段模式。",
    ),
}


@dataclass
class AgentRuntime:
    settings: Settings
    preset_prompt: str = ""
    team_name: str = ""
    selected_skills: dict[AgentId, str] | None = None
    prompt_overrides: dict[AgentId, str] | None = None
    judge_prompt: str = ""
    output_protocol_prompt: str = ""

    def model_for(self, agent_id: AgentId) -> ChatOpenAI:
        model_name = {
            "S": self.settings.agent_s_model,
            "A": self.settings.agent_a_model,
            "B": self.settings.agent_b_model,
            "C": self.settings.agent_c_model,
        }[agent_id]
        base_url = {
            "S": self.settings.agent_s_base_url,
            "A": self.settings.agent_a_base_url,
            "B": self.settings.agent_b_base_url,
            "C": self.settings.agent_c_base_url,
        }[agent_id]
        api_key = {
            "S": self.settings.agent_s_api_key,
            "A": self.settings.agent_a_api_key,
            "B": self.settings.agent_b_api_key,
            "C": self.settings.agent_c_api_key,
        }[agent_id]
        if not api_key:
            raise ValueError("至少需要配置一个 API Key。")
        return ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            streaming=True,
            temperature=0.35,
        ).with_config({"run_name": AGENT_SPECS[agent_id].run_name})

    def summarizer_model(self) -> ChatOpenAI:
        api_key = (
            self.settings.summary_api_key
            or self.settings.agent_s_api_key
            or self.settings.agent_a_api_key
            or self.settings.agent_b_api_key
            or self.settings.agent_c_api_key
        )
        if not api_key:
            raise ValueError("至少需要配置一个 API Key 才能执行总结。")
        return ChatOpenAI(
            api_key=api_key,
            base_url=self.settings.summary_base_url,
            model=self.settings.summary_model,
            temperature=0.2,
        ).with_config({"run_name": "Summarizer"})

    def judge_model(self) -> ChatOpenAI:
        return self.summarizer_model().with_config({"run_name": "Judge"})

    def prompt_for(self, agent_id: AgentId) -> str:
        registry = SkillRegistry(team_name=self.team_name or None)
        skill_id = (self.selected_skills or {}).get(agent_id, "").strip()
        if skill_id:
            skill = registry.get(skill_id)
            if skill and skill.content.strip():
                override = (self.prompt_overrides or {}).get(agent_id, "").strip()
                return f"{skill.content}\n\n## 局部补充\n{override}".strip() if override else skill.content
        override = (self.prompt_overrides or {}).get(agent_id, "").strip()
        return override or AGENT_SPECS[agent_id].system_prompt


_RUNTIME: AgentRuntime | None = None


def configure_agents(
    settings: Settings,
    preset_prompt: str = "",
    team_name: str = "",
    selected_skills: dict[AgentId, str] | None = None,
    prompt_overrides: dict[AgentId, str] | None = None,
    judge_prompt: str = "",
    output_protocol_prompt: str = "",
) -> None:
    global _RUNTIME
    _RUNTIME = AgentRuntime(
        settings=settings,
        preset_prompt=preset_prompt.strip(),
        team_name=team_name.strip(),
        selected_skills=selected_skills or {},
        prompt_overrides=prompt_overrides or {},
        judge_prompt=judge_prompt.strip(),
        output_protocol_prompt=output_protocol_prompt.strip(),
    )


def get_agent_spec(agent_id: AgentId) -> AgentSpec:
    return AGENT_SPECS[agent_id]


def _runtime() -> AgentRuntime:
    if _RUNTIME is None:
        raise RuntimeError("Agents are not configured. Call configure_agents() before building the graph.")
    return _RUNTIME


def build_documents_context(selected_documents_context: str) -> str:
    content = selected_documents_context.strip()
    if not content:
        return "【当前选中文档】\n- 未选择文档"
    return f"【当前选中文档】\n{content}"


def _task_brief_lines(task_brief: TaskBrief) -> list[str]:
    fields = [
        ("目标", task_brief.get("objective", "")),
        ("背景", task_brief.get("background", "")),
        ("任务类型", task_brief.get("task_type", "")),
        ("预算限制", task_brief.get("budget_limit", "")),
        ("时间限制", task_brief.get("time_limit", "")),
        ("已有资源", task_brief.get("existing_assets", "")),
        ("其他约束", task_brief.get("constraints", "")),
        ("成功指标", task_brief.get("success_metric", "")),
        ("失败标准", task_brief.get("failure_criteria", "")),
        ("期望输出", task_brief.get("expected_output", "")),
    ]
    return [f"- {label}: {value}" for label, value in fields if value]


def build_round_mode_instruction(round_mode: RoundMode) -> str:
    mapping = {
        "auto": dedent(
            """
            当前阶段模式：auto
            - 由系统根据用户意图和当前决策阶段自动判断。
            - 如果用户明确要求某种模式，以当前用户意图优先。
            """
        ),
        "diverge": dedent(
            """
            当前阶段模式：diverge
            - 只提出方向，不做完整大方案。
            - 不写长执行清单。
            - 不编造数据。
            - 最多给 3 个方向。
            """
        ),
        "critique": dedent(
            """
            当前阶段模式：critique
            - 只找问题，不扩展新功能。
            - 必须从成本、指标、工程、用户体验、约束违反等角度挑刺。
            - 不允许提出大而全的新方案。
            """
        ),
        "converge": dedent(
            """
            当前阶段模式：converge
            - 必须收敛。
            - 必须输出保留 / 砍掉 / 延后。
            - 必须围绕 task_brief 和 constraint_prompt。
            - 必须给最小可执行方案。
            """
        ),
        "execute": dedent(
            """
            当前阶段模式：execute
            - 只给执行任务。
            - 必须说明改哪些文件 / 哪些接口 / 哪些 UI / 怎么验收。
            - 不继续宏观战略讨论。
            """
        ),
    }
    return mapping.get(round_mode, mapping["converge"]).strip()


def build_task_type_instruction(task_type: str) -> str:
    if not task_type:
        return "任务类型：general。按通用决策协议作答。"
    guidance = {
        "startup_validation": "更关注假设验证、证据缺口和最小试错成本。",
        "product_design": "更关注需求边界、交互取舍和最小可交付范围。",
        "engineering_review": "更关注结构风险、接口边界、回滚与验收。",
        "research_brainstorm": "更关注问题空间、假设分支和待验证点。",
        "business_plan": "更关注资源约束、路径可行性和执行顺序。",
        "ui_review": "更关注信息架构、交互负担和视觉一致性。",
        "personal_decision": "更关注现实约束、机会成本和决策清晰度。",
        "general": "按通用决策协议作答。",
    }
    return f"任务类型：{task_type}。{guidance.get(task_type, guidance['general'])}"


def _decision_memory_lines(memory: DecisionMemory) -> list[str]:
    sections: list[tuple[str, list[str] | str]] = [
        ("本轮摘要", memory.get("round_summary", "")),
        ("已确认决策", memory.get("decisions", [])),
        ("已否决方案", memory.get("rejected_options", [])),
        ("未解决问题", memory.get("open_questions", [])),
        ("下一步动作", memory.get("next_actions", [])),
        ("当前有效约束", memory.get("active_constraints", [])),
    ]
    lines: list[str] = []
    for title, value in sections:
        if isinstance(value, str):
            if value.strip():
                lines.append(f"- {title}: {value.strip()}")
            continue
        if value:
            lines.append(f"- {title}: {'；'.join(item for item in value if item)}")
    return lines


def _normalize_memory_item(value: str) -> str:
    normalized = value.strip()
    normalized = normalized.replace("**", "")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[。．.!！?？]+$", "", normalized)
    normalized = normalized.strip(" -\t")
    return normalized


def _dedupe_items(items: list[str], limit: int | None = None) -> list[str]:
    seen: list[str] = []
    for raw in items:
        item = _normalize_memory_item(raw)
        if not item:
            continue
        if item in seen:
            continue
        seen.append(item)
        if limit is not None and len(seen) >= limit:
            break
    return seen


def _recent_messages_for_context(state: CouncilState, keep_recent_turns: int) -> list[str]:
    recent = state.get("messages", [])[-max(keep_recent_turns * 3, 6) :]
    items: list[str] = []
    for message in recent:
        if isinstance(message, SystemMessage):
            continue
        role = getattr(message, "name", None) or getattr(message, "type", "message")
        content = _coerce_chunk_text(getattr(message, "content", ""))
        if content.strip():
            items.append(f"{role}: {content.strip()}")
    return items[- max(keep_recent_turns * 4, 6) :]


def build_context_packet(state: CouncilState, agent_id: AgentId, user_input: str) -> dict[str, object]:
    decision_memory = state.get("decision_memory", {})
    return {
        "workspace_name": state.get("workspace_name", "").strip() or "默认工作区",
        "workspace_id": state.get("workspace_id", "").strip() or "default",
        "global_constraint": state.get("global_constraint", "").strip() or state.get("constraint_prompt", "").strip(),
        "judge_rubric": state.get("judge_rubric", "").strip() or state.get("judge_prompt", "").strip() or DEFAULT_JUDGE_PROMPT,
        "selected_documents_context": state.get("selected_documents_context", "").strip(),
        "compact_context": state.get("compact_context", "").strip() or state.get("summary", "").strip(),
        "decision_memory": {
            **decision_memory,
            "decisions": _dedupe_items(list(decision_memory.get("decisions", []))),
            "rejected_options": _dedupe_items(list(decision_memory.get("rejected_options", []))),
            "next_actions": _dedupe_items(list(decision_memory.get("next_actions", [])), limit=6),
            "open_questions": _dedupe_items(list(decision_memory.get("open_questions", [])), limit=6),
            "active_constraints": _dedupe_items(list(decision_memory.get("active_constraints", [])), limit=8),
        },
        "recent_messages": _recent_messages_for_context(state, max(int(state.get("keep_recent_turns", 3) or 3), 1)),
        "round_mode": state.get("round_mode", "converge"),
        "auto_mode": bool(state.get("auto_mode", True)),
        "task_brief": state.get("task_brief", {}),
        "project_prompt": state.get("project_prompt", "").strip(),
        "preset_prompt": state.get("preset_prompt", "").strip() or _runtime().preset_prompt,
        "output_protocol_prompt": state.get("output_protocol_prompt", "").strip() or _runtime().output_protocol_prompt,
        "agent_role": AGENT_SPECS[agent_id].display_name,
        "user_input": user_input.strip(),
    }


def build_protocol_context(state: CouncilState, agent_id: AgentId) -> str:
    packet = build_context_packet(state, agent_id, state.get("human_input", ""))
    task_brief = state.get("task_brief", {})
    decision_memory = packet["decision_memory"]
    lines = [
        "【决策协议上下文】",
        f"- 当前工作区: {packet['workspace_name']}",
        f"- 工作区 ID: {packet['workspace_id']}",
        f"- 当前角色: {AGENT_SPECS[agent_id].display_name}",
        f"- 激活 Agent: {', '.join(state.get('active_agents', DEFAULT_ACTIVE_AGENTS))}",
        f"- round_mode: {packet['round_mode']}",
        f"- auto_mode: {'true' if packet['auto_mode'] else 'false'}",
        f"- enable_judge: {'true' if state.get('enable_judge', True) else 'false'}",
    ]
    preset_prompt = str(packet["preset_prompt"])
    if preset_prompt:
        lines.extend(["", "【预设提示词】", preset_prompt])
    constraint_prompt = str(packet["global_constraint"])
    if constraint_prompt:
        lines.extend(["", "【项目全局约束 / Global Constraint】", constraint_prompt])
    project_prompt = str(packet["project_prompt"])
    if project_prompt:
        lines.extend(["", "【项目背景提示词 / Project Prompt】", project_prompt])
    task_brief_lines = _task_brief_lines(task_brief)
    if task_brief_lines:
        lines.extend(["", "【Task Brief】", *task_brief_lines])
    lines.extend(["", build_documents_context(str(packet["selected_documents_context"]))])
    compact_context = str(packet["compact_context"])
    if compact_context:
        lines.extend(["", "【Compact Context】", compact_context])
    lines.extend(["", "【阶段模式要求】", build_round_mode_instruction(state.get("round_mode", "converge"))])
    lines.extend(["", "【任务类型提示】", build_task_type_instruction(task_brief.get("task_type", "general"))])
    memory_lines = _decision_memory_lines(decision_memory)  # type: ignore[arg-type]
    if memory_lines:
        lines.extend(["", "【Decision Memory】", *memory_lines])
    recent_messages = list(packet["recent_messages"])
    if recent_messages:
        lines.extend(["", "【Recent Messages】", *[f"- {item}" for item in recent_messages]])
    output_protocol = state.get("output_protocol_prompt", "").strip() or _runtime().output_protocol_prompt
    if output_protocol:
        lines.extend(["", "【输出协议】", output_protocol])
    lines.extend(
        [
            "",
            "【本 Agent 附加要求】",
            "- 如果已否决方案中存在相近思路，不要重复提出。",
            "- 如果你的默认 skill 倾向与阶段模式冲突，以阶段模式为准。",
            "- 如果约束提示词与 skill 人设冲突，以约束提示词为准。",
        ]
    )
    return "\n".join(lines).strip()


def _build_conversation(state: CouncilState, agent_id: AgentId) -> list[BaseMessage]:
    spec = get_agent_spec(agent_id)
    runtime = _runtime()
    compact_context = state.get("compact_context", "").strip() or state.get("summary", "").strip()
    summary_block = f"\n【压缩上下文】\n{compact_context}\n" if compact_context else ""
    instruction = dedent(
        f"""
        你当前代表 {spec.display_name}。
        用户本轮输入：
        {state.get("human_input", "").strip() or "无"}
        {summary_block}
        你可以参考最近对话，但必须先遵守协议上下文，再结合 skill 人设发言。
        你的职责是推进问题，而不是重复前文。
        """
    ).strip()

    formatted_messages: list[BaseMessage] = [
        SystemMessage(content=BASE_SAFETY_PROMPT),
        SystemMessage(content=build_protocol_context(state, agent_id)),
        SystemMessage(content=runtime.prompt_for(agent_id)),
    ]
    for item in _recent_messages_for_context(state, max(int(state.get("keep_recent_turns", 3) or 3), 1)):
        formatted_messages.append(HumanMessage(content=f"【最近上下文】\n{item}"))
    formatted_messages.append(HumanMessage(content=instruction))
    return formatted_messages


async def _run_agent(agent_id: AgentId, state: CouncilState) -> CouncilState:
    response = await _runtime().model_for(agent_id).ainvoke(_build_conversation(state, agent_id))
    return {
        "messages": [
            build_agent_ai_message(
                agent_id,
                _coerce_chunk_text(response.content),
                _extract_reasoning(getattr(response, "additional_kwargs", {})),
            )
        ]
    }


def _coerce_chunk_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return str(content or "")


def _extract_reasoning_from_content(content: object) -> str:
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            for key in ("reasoning_content", "reasoning", "thinking", "thought"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    chunks.append(value)
            if item.get("type") in {"reasoning", "thinking"}:
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text:
                    chunks.append(text)
        return "".join(chunks)
    return ""


def build_agent_ai_message(agent_id: AgentId, content: str, reasoning: str = "") -> AIMessage:
    spec = get_agent_spec(agent_id)
    return AIMessage(
        content=content,
        name=spec.node_name,
        id=f"{agent_id}-{uuid4().hex}",
        additional_kwargs={"agent_id": agent_id, "display_name": spec.display_name, "reasoning_content": reasoning},
    )


def build_judge_ai_message(content: str) -> AIMessage:
    return AIMessage(
        content=content,
        name=JUDGE_NODE_NAME,
        id=f"judge-{uuid4().hex}",
        additional_kwargs={"agent_id": "JUDGE", "display_name": JUDGE_DISPLAY_NAME, "reasoning_content": ""},
    )


def _extract_reasoning(extra: object) -> str:
    if isinstance(extra, dict):
        for key in ("reasoning_content", "reasoning", "thinking", "thought"):
            value = extra.get(key)
            if isinstance(value, str) and value:
                return value
        metadata = extra.get("response_metadata")
        if isinstance(metadata, dict):
            for key in ("reasoning_content", "reasoning", "thinking", "thought"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    return value
    return ""


async def stream_agent_reply(agent_id: AgentId, state: CouncilState) -> AsyncIterator[dict[str, str]]:
    async for chunk in _runtime().model_for(agent_id).astream(_build_conversation(state, agent_id)):
        text = ""
        reasoning = ""
        if isinstance(chunk, AIMessageChunk):
            text = _coerce_chunk_text(chunk.content)
            reasoning = _extract_reasoning_from_content(chunk.content) or _extract_reasoning(getattr(chunk, "additional_kwargs", {}))
        else:
            text = _coerce_chunk_text(getattr(chunk, "content", chunk))
            reasoning = _extract_reasoning_from_content(getattr(chunk, "content", "")) or _extract_reasoning(getattr(chunk, "additional_kwargs", {}))
        if reasoning:
            yield {"channel": "reasoning", "delta": reasoning}
        if text:
            yield {"channel": "content", "delta": text}


def _build_judge_messages(state: CouncilState) -> list[BaseMessage]:
    runtime = _runtime()
    packet = build_context_packet(state, "S", state.get("human_input", ""))
    task_brief_lines = _task_brief_lines(state.get("task_brief", {}))
    memory_lines = _decision_memory_lines(packet["decision_memory"])  # type: ignore[arg-type]
    transcript_lines: list[str] = []
    for line in list(packet["recent_messages"]):
        transcript_lines.append(line)
    for message in state.get("messages", [])[-8:]:
        if not isinstance(message, AIMessage):
            continue
        agent_id = message.additional_kwargs.get("agent_id")
        if agent_id not in {"S", "A", "B", "C"}:
            continue
        transcript_lines.append(f"【{message.additional_kwargs.get('display_name', agent_id)}】\n{message.content}")
    user_prompt = dedent(
        f"""
        【当前工作区】
        - 名称: {packet['workspace_name']}
        - ID: {packet['workspace_id']}
        - round_mode: {packet['round_mode']}
        - auto_mode: {'true' if packet['auto_mode'] else 'false'}

        【用户本轮问题】
        {state.get('human_input', '').strip() or '无'}

        【项目全局约束 / Global Constraint】
        {packet['global_constraint'] or '未提供'}

        【Judge 判断标准 / Judge Rubric】
        {packet['judge_rubric'] or '未提供'}

        【项目背景提示词 / Project Prompt】
        {state.get('project_prompt', '').strip() or '未提供'}

        【Task Brief】
        {chr(10).join(task_brief_lines) if task_brief_lines else '- 未提供'}

        {build_documents_context(str(packet['selected_documents_context']))}

        【Compact Context】
        {packet['compact_context'] or '暂无'}

        【Decision Memory】
        {chr(10).join(memory_lines) if memory_lines else '- 暂无'}

        【最近消息与本轮输出】
        {chr(10).join(transcript_lines) if transcript_lines else '无'}
        """
    ).strip()
    judge_prompt = state.get("judge_rubric", "").strip() or runtime.judge_prompt or state.get("judge_prompt", "").strip() or DEFAULT_JUDGE_PROMPT
    return [SystemMessage(content=BASE_SAFETY_PROMPT), SystemMessage(content=judge_prompt), HumanMessage(content=user_prompt)]


async def run_judge(state: CouncilState) -> str:
    response = await _runtime().judge_model().ainvoke(_build_judge_messages(state))
    return _coerce_chunk_text(response.content).strip()


async def node_judge(state: CouncilState) -> CouncilState:
    if not state.get("enable_judge", True):
        return {}
    try:
        content = await run_judge(state)
    except Exception as exc:
        content = (
            "【是否跑偏】\n- 否\n- 原因：Judge 执行失败，已跳过本轮裁判收敛。\n\n"
            f"【需要用户补充的信息】\n1. Judge 错误：{exc}\n\n【下一轮建议提问】\n确认是否重试 Judge。"
        )
    return {"messages": [build_judge_ai_message(content)], "judge_output": content}


def _extract_section(text: str, title: str) -> str:
    pattern = rf"【{re.escape(title)}】\s*(.*?)(?=\n【|$)"
    match = re.search(pattern, text, re.S)
    return match.group(1).strip() if match else ""


def _extract_list_items(block: str) -> list[str]:
    items: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s*", "", line)
        line = re.sub(r"^\d+\.\s*", "", line)
        line = line.strip()
        if line and line not in {"无", "暂无", "无。"}:
            items.append(line)
    return _dedupe_items(items)


def extract_judge_json(judge_output: str) -> dict[str, list[str]] | None:
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", judge_output, re.S)
    candidate = fenced.group(1) if fenced else None
    if not candidate:
        inline = re.search(r'(\{\s*"confirmed_decisions".*?\})', judge_output, re.S)
        candidate = inline.group(1) if inline else None
    if not candidate:
        return None
    try:
        payload = json.loads(candidate)
    except Exception:
        return None
    result: dict[str, list[str]] = {}
    for key in (
        "confirmed_decisions",
        "rejected_options",
        "next_actions",
        "open_questions",
        "must_cut",
        "minimal_plan",
        "needs_user_input",
    ):
        value = payload.get(key, [])
        if isinstance(value, list):
            result[key] = _dedupe_items([str(item) for item in value])
        else:
            result[key] = []
    return result


def decision_memory_from_judge_output(judge_output: str, fallback_constraints: str = "") -> DecisionMemory:
    json_payload = extract_judge_json(judge_output)
    confirmed = json_payload.get("confirmed_decisions", []) if json_payload else _extract_list_items(_extract_section(judge_output, "已确认决策"))
    rejected = json_payload.get("rejected_options", []) if json_payload else _extract_list_items(_extract_section(judge_output, "已否决方案"))
    next_actions = json_payload.get("next_actions", []) if json_payload else _extract_list_items(_extract_section(judge_output, "下一步动作"))
    open_questions = json_payload.get("open_questions", []) if json_payload else _extract_list_items(_extract_section(judge_output, "需要用户补充的信息"))
    minimal_plan = json_payload.get("minimal_plan", []) if json_payload else _extract_list_items(_extract_section(judge_output, "保留的最小方案"))
    active_constraints = _dedupe_items(_extract_list_items(fallback_constraints))
    return {
        "round_summary": "；".join(minimal_plan[:3]),
        "decisions": _dedupe_items(confirmed),
        "rejected_options": _dedupe_items(rejected),
        "open_questions": _dedupe_items(open_questions),
        "next_actions": _dedupe_items(next_actions, limit=6),
        "active_constraints": active_constraints,
        "updated_at": datetime.utcnow().isoformat(),
    }


def merge_decision_memory(current: DecisionMemory | None, judge_output: str, fallback_constraints: str = "") -> DecisionMemory:
    current = current or {}
    parsed = decision_memory_from_judge_output(judge_output, fallback_constraints=fallback_constraints)

    def merged_list(key: str) -> list[str]:
        seen: list[str] = []
        for source in (current.get(key, []), parsed.get(key, [])):
            for item in source:
                if item and item not in seen:
                    seen.append(item)
        return seen

    return {
        "round_summary": parsed.get("round_summary") or current.get("round_summary", ""),
        "decisions": merged_list("decisions"),
        "rejected_options": merged_list("rejected_options"),
        "open_questions": merged_list("open_questions"),
        "next_actions": _dedupe_items(parsed.get("next_actions", []) or current.get("next_actions", []), limit=6),
        "active_constraints": _dedupe_items(parsed.get("active_constraints") or current.get("active_constraints", []), limit=8),
        "updated_at": parsed.get("updated_at", datetime.utcnow().isoformat()),
    }


async def node_update_decision_memory(state: CouncilState) -> CouncilState:
    judge_output = state.get("judge_output", "").strip()
    if not judge_output:
        return {}
    return {
        "decision_memory": merge_decision_memory(
            state.get("decision_memory", {}),
            judge_output,
            fallback_constraints=state.get("constraint_prompt", ""),
        )
    }


async def node_agent_s(state: CouncilState) -> CouncilState:
    return await _run_agent("S", state)


async def node_agent_a(state: CouncilState) -> CouncilState:
    return await _run_agent("A", state)


async def node_agent_b(state: CouncilState) -> CouncilState:
    return await _run_agent("B", state)


async def node_agent_c(state: CouncilState) -> CouncilState:
    return await _run_agent("C", state)


async def node_summarizer(state: CouncilState) -> CouncilState:
    runtime = _runtime()
    messages = state.get("messages", [])
    recent_messages = messages[-8:]
    transcript = "\n".join(f"{getattr(message, 'name', None) or message.type}: {message.content}" for message in recent_messages)
    prompt = dedent(
        f"""
        你是后台总结节点。请合并旧摘要和最近消息，产出新的长期记忆。
        输出要求：
        1. 使用 6 到 12 条 Markdown 列表。
        2. 只保留已确认约束、背景、结论、风险、待办。
        3. 删除过时内容和重复说法。

        旧摘要:
        {state.get("compact_context", "").strip() or state.get("summary", "").strip() or "无"}

        最近消息:
        {transcript or "无"}

        当前结构化决策记忆:
        {json.dumps(state.get("decision_memory", {}), ensure_ascii=False)}
        """
    ).strip()
    response = await runtime.summarizer_model().ainvoke(
        [SystemMessage(content="你负责多智能体系统的长期记忆压缩。"), HumanMessage(content=prompt)]
    )
    removable = [message for message in messages[:-4] if getattr(message, "id", None)]
    return {
        "summary": str(response.content).strip(),
        "compact_context": str(response.content).strip(),
        "messages": [RemoveMessage(id=message.id) for message in removable],
    }


def generate_export_bundle(project_name: str, summary: str, messages: list[HumanMessage | AIMessage]) -> dict[str, str]:
    runtime = _runtime()
    transcript = "\n".join(f"{getattr(message, 'name', None) or message.type}: {message.content}" for message in messages[-12:])
    prompt = dedent(
        f"""
        你是 DocumentAgent。请生成导出文档。
        输出 JSON，字段：
        - markdown: 完整 Markdown 文档，包含背景、当前共识、关键风险、下一步行动。
        - mermaid: Mermaid flowchart TD 代码，只输出图代码，不要围栏。

        项目名: {project_name}
        当前摘要:
        {summary or "无"}

        最近对话:
        {transcript or "无"}
        """
    ).strip()
    response = runtime.summarizer_model().invoke(
        [SystemMessage(content="你负责生成结构化文档。只返回合法 JSON。"), HumanMessage(content=prompt)]
    )
    try:
        payload = json.loads(str(response.content))
        markdown = str(payload.get("markdown", "")).strip()
        mermaid = str(payload.get("mermaid", "")).strip()
    except Exception:
        markdown = ""
        mermaid = ""

    if not markdown:
        markdown = dedent(
            f"""
            # {project_name}

            ## 当前摘要
            {summary or "待补充"}

            ## 最近对话摘录
            ```text
            {transcript or "无"}
            ```
            """
        ).strip()
    if not mermaid:
        mermaid = (
            "flowchart TD\n"
            "    Human[Control Center] --> Router[Router]\n"
            "    Router --> S[Agent S]\n"
            "    S --> A[Agent A]\n"
            "    A --> B[Agent B]\n"
            "    B --> C[Agent C]\n"
            "    C --> Judge[Judge]\n"
            "    Judge --> Summary[Summarizer]"
        )
    return {"markdown": markdown, "mermaid": mermaid}
