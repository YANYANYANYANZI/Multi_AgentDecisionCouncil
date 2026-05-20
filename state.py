from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


AgentId = Literal["S", "A", "B", "C"]


class CouncilState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    human_input: str
    active_agents: list[AgentId]
    summary: str
