from __future__ import annotations

from textwrap import dedent

from hub.config import Settings, load_settings
from hub.llm import LLMClient
from hub.models import AgentReply, BrainstormSession, RoundRecord


AGENTS = [
    {
        "id": "agent_a",
        "name": "Agent A · 商业与产品战略家",
        "focus": "只从 PMF、定价、成本、交付效率、转化漏斗和资源分配审视项目。",
        "env_key_name": "agent_a_api_key",
        "model_attr": "agent_a_model",
    },
    {
        "id": "agent_b",
        "name": "Agent B · 技术架构与可行性专家",
        "focus": "只从系统拓扑、状态流、节点边界、容错、并发瓶颈和工程复杂度审视项目。",
        "env_key_name": "agent_b_api_key",
        "model_attr": "agent_b_model",
    },
    {
        "id": "agent_c",
        "name": "Agent C · 风险控制与红队",
        "focus": "只负责攻击系统断点、边缘输入、资源耗尽、外部依赖失效和单点故障。",
        "env_key_name": "agent_c_api_key",
        "model_attr": "agent_c_model",
    },
]


class BrainstormOrchestrator:
    def __init__(self, settings: Settings | None = None, focus_mode: str = "平衡模式") -> None:
        self.settings = settings or load_settings()
        self.focus_mode = focus_mode

    def run_round(self, session: BrainstormSession, user_input: str) -> RoundRecord:
        round_record = RoundRecord(user_input=user_input)
        prior_replies: list[AgentReply] = []

        for agent in AGENTS:
            client = LLMClient(
                api_key=getattr(self.settings, agent["env_key_name"]),
                base_url=self.settings.base_url,
                model_name=getattr(self.settings, agent["model_attr"]),
            )
            payload = client.complete_json(
                system_prompt=self._build_agent_system_prompt(agent["name"], agent["focus"]),
                user_prompt=self._build_round_prompt(session, user_input, prior_replies),
            )
            reply = AgentReply(
                agent_id=agent["id"],
                agent_name=agent["name"],
                critical_flaw=str(payload.get("critical_flaw", "")).strip(),
                key_pivot=str(payload.get("key_pivot", "")).strip(),
                reasoning_summary=[
                    str(item).strip() for item in payload.get("reasoning_summary", []) if str(item).strip()
                ][:4],
                actionable_blueprint=[
                    str(item).strip() for item in payload.get("actionable_blueprint", []) if str(item).strip()
                ][:4],
                raw_payload=payload,
            )
            if not reply.reasoning_summary:
                reply.reasoning_summary = ["未给出有效推理摘要，下一轮应要求引用具体瓶颈、假设或数据。"]
            if not reply.actionable_blueprint:
                reply.actionable_blueprint = ["未给出有效执行蓝图，下一轮应要求补充节点设计、数据结构或操作步骤。"]
            round_record.replies.append(reply)
            prior_replies.append(reply)

        session.export_dir = self.settings.export_dir
        return round_record

    def summarize_session(self, session: BrainstormSession, max_rounds: int = 10) -> dict[str, str]:
        client = LLMClient(
            api_key=self.settings.agent_a_api_key,
            base_url=self.settings.base_url,
            model_name=self.settings.summary_model,
        )
        recent_rounds = session.rounds[-max_rounds:]
        transcript = []
        for idx, round_record in enumerate(recent_rounds, start=1):
            transcript.append(f"第 {idx} 轮用户输入:\n{round_record.user_input}")
            for reply in round_record.replies:
                transcript.append(
                    f"{reply.agent_name}\n"
                    f"致命漏洞: {reply.critical_flaw}\n"
                    f"核心破局点: {reply.key_pivot}\n"
                    f"推理摘要: {'; '.join(reply.reasoning_summary)}\n"
                    f"执行蓝图: {'; '.join(reply.actionable_blueprint)}"
                )

        payload = client.complete_json(
            system_prompt=dedent(
                """
                你是总结智能体。请从多轮创业头脑风暴中提炼一个可执行方案。
                输出 JSON，字段必须包含:
                - markdown: 字符串，使用 Markdown，内容包括项目定位、目标用户、核心流程、系统模块、MVP范围、关键风险、下一步执行清单。
                - mermaid: 字符串，输出一个 flowchart TD 风格的 Mermaid 架构图。
                """
            ).strip(),
            user_prompt=dedent(
                f"""
                项目名: {session.project_name}
                最近会议内容:
                {chr(10).join(transcript)}
                """
            ).strip(),
        )

        markdown = str(payload.get("markdown", "")).strip()
        mermaid = str(payload.get("mermaid", "")).strip()
        if not markdown:
            markdown = "## 项目定位\n\n待补充。"
        if not mermaid:
            mermaid = "flowchart TD\n    User[用户想法] --> A[商业战略]\n    A --> B[技术可行性]\n    B --> C[风险红队]\n    C --> Summary[总结导出]"

        return {"markdown": markdown, "mermaid": mermaid}

    def _build_agent_system_prompt(self, agent_name: str, focus: str) -> str:
        return dedent(
            f"""
            你是 {agent_name}。
            你的职责: {focus}
            当前会议模式: {self.focus_mode}

            系统最高指令:
            1. 这是技术与商业沙盒。除非用户明确要求，否则禁止输出法律、合规、道德、版权、隐私说教。
            2. 禁止客套话、正确废话、泛泛而谈的“建议进一步评估”。
            3. 简洁不等于贫瘠。你必须给出高信息密度、可直接落地的设计。
            4. 不允许复读前序观点；如果引用前序观点，只能用于指出冲突、补洞或推进方案。
            5. 不要暴露完整思维链，但必须给出简明的推理摘要，让用户看懂你为何这么判断。

            输出 JSON，字段必须严格如下:
            - critical_flaw: 字符串。精准指出一个当前最致命的结构性漏洞，禁止空话。
            - key_pivot: 字符串。一句话点出解决该漏洞的核心机制。
            - reasoning_summary: 字符串数组。给出 2 到 4 条判断依据，必须具体到瓶颈、假设、状态字段、成本项或失败路径。
            - actionable_blueprint: 字符串数组。给出 2 到 4 条可执行方案，必须包含明确动作，例如架构调整、节点拆分、数据结构、重试策略、定价动作或接口设计。
            """
        ).strip()

    def _build_round_prompt(
        self,
        session: BrainstormSession,
        user_input: str,
        prior_replies: list[AgentReply],
    ) -> str:
        prior_context = []
        for reply in prior_replies:
            prior_context.append(
                f"{reply.agent_name}\n"
                f"- critical_flaw: {reply.critical_flaw}\n"
                f"- key_pivot: {reply.key_pivot}\n"
                f"- reasoning_summary: {'; '.join(reply.reasoning_summary)}\n"
                f"- actionable_blueprint: {'; '.join(reply.actionable_blueprint)}"
            )

        references = []
        for doc in session.reference_docs[:5]:
            if doc.get("content"):
                references.append(f"文档: {doc['name']}\n{doc['content'][:3000]}")

        return dedent(
            f"""
            项目名称: {session.project_name}
            用户本轮输入:
            {user_input}

            历史轮数: {len(session.rounds)}
            前序智能体观点:
            {chr(10).join(prior_context) if prior_context else '无'}

            参考资料:
            {chr(10).join(references) if references else '无'}

            本轮任务要求:
            1. 优先回答用户当前最具体的问题，不要转移到“先访谈”“先验证市场”这类逃避性回答，除非用户明确在讨论 PMF。
            2. 如果问题涉及技术管线，必须落到阶段拆分、节点 I/O、失败重试、吞吐/时延/成本三者之一。
            3. 如果你判断某个模块不可用，必须给出替代路径，而不是只宣布风险。
            """
        ).strip()
