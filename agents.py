from __future__ import annotations

import json
from dataclasses import dataclass
from textwrap import dedent
from uuid import uuid4

from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_openai import ChatOpenAI

from hub.config import Settings
from skill_registry import SkillRegistry
from state import AgentId, CouncilState


DEFAULT_ACTIVE_AGENTS: list[AgentId] = ["S", "A", "B", "C"]
AGENT_ORDER: tuple[AgentId, ...] = ("S", "A", "B", "C")
ABSOLUTE_DIRECTIVES = dedent(
    """
    【绝对强制约束 - 违者熔断】：
    1. 严禁数据幻觉 (No Fabricated Data)：绝对不允许编造不存在的遥测数据、百分比、规则数量或毫秒级延迟！如果你没有真实运行环境的数据支撑，只能进行定性分析，禁止凭空捏造定量数据。
    2. 严禁极端降级 (No Absurd Engineering)：提倡传统代码不等于退化为弱智代码。学术逻辑冲突、深层语义去重等复杂 NLP 场景，绝对禁止提出“用几十个词典+正则表达式覆盖”这种违背工程常识的方案；如果传统代码无法高可靠解决，必须诚实地保留大模型节点。
    3. 严禁复读与顺从 (No Parroting)：你的工作是找茬和建设。如果前面的 Agent 已经提出了某个方案，你绝对不能重复它的观点；如果你找不出漏洞，你必须从自己的专业视角提出前人完全没有想到的全新扩展维度。
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
        display_name="S·首席架构师",
        avatar="👑",
        color="#4F46E5",
        system_prompt="你是系统的大脑，负责根据用户指令提出架构初稿，并吸收委员会意见进行迭代。",
    ),
    "A": AgentSpec(
        agent_id="A",
        node_name="agent_a",
        run_name="Agent_A",
        display_name="A·商业战略家",
        avatar="💼",
        color="#D97706",
        system_prompt=dedent(
            f"""
            [当前角色：Agent A · 业务管线与成本精算师]
            【最高红线】：系统已经有完美的获客渠道和商业闭环！绝对禁止讨论“如何获客”“市场信任”“产品定价策略”“是否伪需求”以及“人工兜底模式”。如果你打算讨论这些，立即停止并回到工程履约问题。
            【你的任务】：你必须假设订单已经疯狂涌入，你的唯一目标是盯着机器管线的交付履约。
            你的视角仅限于：
            1. Unit Economics：API Token 消耗压降、并发服务器计算成本、单位订单履约成本。
            2. SLA 保障：外部 API 挂掉时的重试、超时、降级、回退链路对交付时间的影响。
            3. 吞吐量优化：系统架构层面的并行处理能力、队列积压、瓶颈环节和扩缩容限制。
            请根据具体工程链路输出漏洞挖掘与架构设计。禁止商业说教，禁止市场分析。
            {ABSOLUTE_DIRECTIVES}

            输出格式必须使用以下模块标题:
            [致命漏洞]
            [核心破局点]
            [可执行蓝图]
            """
        ).strip(),
    ),
    "B": AgentSpec(
        agent_id="B",
        node_name="agent_b",
        run_name="Agent_B",
        display_name="B·架构专家",
        avatar="🛠️",
        color="#0891B2",
        system_prompt=dedent(
            f"""
            你是 B·架构专家。
            你只从技术架构、模块边界、状态流、并发、容错、数据结构、工程复杂度角度发言。
            【工程红线】：
            1. 能用正则、普通 SQL、简单 Python 代码解决的问题，绝对不许调模型。
            2. 优先使用成熟工业标准组件，慎用不适合高频事务的技术栈。
            3. 每次提出技术栈或模块，必须说明当前并发/成本约束下的最坏情况。
            {ABSOLUTE_DIRECTIVES}

            输出格式必须使用以下模块标题:
            [致命漏洞]
            [核心破局点]
            [可执行蓝图]
            """
        ).strip(),
    ),
    "C": AgentSpec(
        agent_id="C",
        node_name="agent_c",
        run_name="Agent_C",
        display_name="C·风控红队",
        avatar="🛡️",
        color="#B91C1C",
        system_prompt=dedent(
            f"""
            你是 C·风控红队。
            你只负责寻找隐藏风险、单点故障、资源耗尽、边界输入、依赖失效、商业与技术假设中的脆弱点。
            你的输出必须尖锐、具体，不能停留在抽象提醒。
            {ABSOLUTE_DIRECTIVES}

            输出格式必须使用以下模块标题:
            [致命漏洞]
            [核心破局点]
            [可执行蓝图]
            """
        ).strip(),
    ),
}


@dataclass
class AgentRuntime:
    settings: Settings
    preset_prompt: str = ""
    selected_skills: dict[AgentId, str] | None = None
    prompt_overrides: dict[AgentId, str] | None = None

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
            raise ValueError("至少需要配置一个 API Key。请在 `.env` 中填写 `SHARED_DEEPSEEK_API_KEY` 或三个 Agent 独立 Key。")
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
            raise ValueError("至少需要配置一个 API Key 才能执行总结与导出。")
        return ChatOpenAI(
            api_key=api_key,
            base_url=self.settings.summary_base_url,
            model=self.settings.summary_model,
            temperature=0.2,
        ).with_config({"run_name": "Summarizer"})

    def prompt_for(self, agent_id: AgentId) -> str:
        registry = SkillRegistry()
        skill_id = (self.selected_skills or {}).get(agent_id, "").strip()
        if skill_id:
            skill = registry.get(skill_id)
            if skill and skill.content.strip():
                override = (self.prompt_overrides or {}).get(agent_id, "").strip()
                return f"{skill.content}\n\n## 附加覆盖\n{override}".strip() if override else skill.content
        override = (self.prompt_overrides or {}).get(agent_id, "").strip()
        return override or AGENT_SPECS[agent_id].system_prompt


_RUNTIME: AgentRuntime | None = None


def configure_agents(
    settings: Settings,
    preset_prompt: str = "",
    selected_skills: dict[AgentId, str] | None = None,
    prompt_overrides: dict[AgentId, str] | None = None,
) -> None:
    global _RUNTIME
    _RUNTIME = AgentRuntime(
        settings=settings,
        preset_prompt=preset_prompt.strip(),
        selected_skills=selected_skills or {},
        prompt_overrides=prompt_overrides or {},
    )


def get_agent_spec(agent_id: AgentId) -> AgentSpec:
    return AGENT_SPECS[agent_id]


def _runtime() -> AgentRuntime:
    if _RUNTIME is None:
        raise RuntimeError("Agents are not configured. Call configure_agents() before building the graph.")
    return _RUNTIME


def _build_conversation(state: CouncilState, agent_id: AgentId) -> list[BaseMessage]:
    spec = get_agent_spec(agent_id)
    runtime = _runtime()
    summary = state.get("summary", "").strip()
    summary_block = f"\n当前系统已确认的架构摘要:\n{summary}\n" if summary else ""
    preset_block = f"\n预设提示:\n{runtime.preset_prompt}\n" if runtime.preset_prompt else ""
    instruction = dedent(
        f"""
        你当前代表 {spec.display_name}。
        本轮被激活的角色: {", ".join(state.get("active_agents", DEFAULT_ACTIVE_AGENTS))}
        用户本轮输入:
        {state.get("human_input", "").strip()}
        {summary_block}
        {preset_block}
        你可以参考最近两轮对话，但只能从你的角色职责发言。
        你的工作是严格审查前文、补充盲点并推进方案，不要复读其他 Agent 的观点。
        """
    ).strip()

    formatted_messages: list[BaseMessage] = [SystemMessage(content=runtime.prompt_for(agent_id))]
    raw_history = state.get("messages", [])
    for message in raw_history:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, AIMessage):
            if getattr(message, "name", "") != spec.node_name:
                sender = message.additional_kwargs.get("display_name", message.name or "其他智能体")
                formatted_messages.append(
                    HumanMessage(content=f"【以下是 {sender} 的方案/发言，请严格审查其漏洞】:\n{message.content}")
                )
            else:
                formatted_messages.append(message)
            continue
        formatted_messages.append(message)

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
    recent_messages = messages[-6:]
    transcript = "\n".join(
        f"{getattr(message, 'name', None) or message.type}: {message.content}" for message in recent_messages
    )
    prompt = dedent(
        f"""
        你是后台总结节点。请合并旧摘要和最近消息，产出新的长期记忆。
        输出要求：
        1. 使用 6 到 12 条 Markdown 列表。
        2. 只保留已确认架构、关键约束、未决风险、已达成共识。
        3. 删除过时内容和重复说法。

        旧摘要:
        {state.get("summary", "").strip() or "无"}

        最近消息:
        {transcript or "无"}
        """
    ).strip()
    response = await runtime.summarizer_model().ainvoke(
        [SystemMessage(content="你负责多智能体系统的长期记忆压缩。"), HumanMessage(content=prompt)]
    )
    removable = [message for message in messages[:-4] if getattr(message, "id", None)]
    return {
        "summary": str(response.content).strip(),
        "messages": [RemoveMessage(id=message.id) for message in removable],
    }


def generate_export_bundle(project_name: str, summary: str, messages: list[HumanMessage | AIMessage]) -> dict[str, str]:
    runtime = _runtime()
    transcript = "\n".join(
        f"{getattr(message, 'name', None) or message.type}: {message.content}" for message in messages[-12:]
    )
    prompt = dedent(
        f"""
        你是 DocumentAgent。请生成导出文档。
        输出 JSON，字段：
        - markdown: 完整 Markdown 文档，包含项目目标、当前架构共识、关键风险、下一步行动。
        - mermaid: Mermaid flowchart TD 代码，只输出图代码，不要围栏。

        项目名: {project_name}
        当前摘要:
        {summary or "无"}

        最近对话:
        {transcript or "无"}
        """
    ).strip()
    response = runtime.summarizer_model().invoke(
        [SystemMessage(content="你负责生成结构化架构文档。只返回合法 JSON。"), HumanMessage(content=prompt)]
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

            ## 当前架构摘要
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
            "    Human[控制中心] --> Router[Router]\n"
            "    Router --> S[Agent S]\n"
            "    S --> A[Agent A]\n"
            "    A --> B[Agent B]\n"
            "    B --> C[Agent C]\n"
            "    C --> Summary[Summarizer]"
        )
    return {"markdown": markdown, "mermaid": mermaid}
