from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


AgentId = Literal["S", "A", "B", "C"]
RoundMode = Literal["auto", "diverge", "critique", "converge", "execute"]
TaskType = Literal[
    "startup_validation",
    "product_design",
    "engineering_review",
    "research_brainstorm",
    "business_plan",
    "ui_review",
    "personal_decision",
    "general",
]


class TaskBrief(TypedDict, total=False):
    objective: str
    background: str
    task_type: TaskType
    budget_limit: str
    time_limit: str
    existing_assets: str
    constraints: str
    success_metric: str
    failure_criteria: str
    expected_output: str


class DecisionMemory(TypedDict, total=False):
    round_summary: str
    decisions: list[str]
    rejected_options: list[str]
    open_questions: list[str]
    next_actions: list[str]
    active_constraints: list[str]
    updated_at: str


class CouncilState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    human_input: str
    active_agents: list[AgentId]
    summary: str
    workspace_id: str
    workspace_name: str
    preset_prompt: str
    global_constraint: str
    constraint_prompt: str
    judge_rubric: str
    project_prompt: str
    judge_prompt: str
    output_protocol_prompt: str
    task_brief: TaskBrief
    selected_documents: list[str]
    selected_documents_context: str
    compact_context: str
    summary_enabled: bool
    auto_mode: bool
    auto_compress_enabled: bool
    auto_compress_turn_threshold: int
    auto_compress_char_threshold: int
    keep_recent_turns: int
    round_mode: RoundMode
    enable_judge: bool
    decision_memory: DecisionMemory
    judge_output: str
