from __future__ import annotations

import re
from collections.abc import Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents import (
    AGENT_ORDER,
    DEFAULT_ACTIVE_AGENTS,
    configure_agents,
    node_agent_s,
    node_agent_a,
    node_agent_b,
    node_agent_c,
    node_summarizer,
)
from hub.config import Settings
from state import AgentId, CouncilState


def parse_active_agents(human_input: str) -> list[AgentId]:
    normalized = (
        human_input.upper()
        .replace("，", ",")
        .replace("、", ",")
        .replace("和", ",")
        .replace("及", ",")
    )
    all_agents: list[AgentId] = list(DEFAULT_ACTIVE_AGENTS)

    include_match = re.search(r"(?:只要|只需|仅需|仅让|只让|ONLY)\s*([SABC,\s]+)", normalized)
    if include_match:
        selected = _extract_agents(include_match.group(1))
        if selected:
            return selected

    excluded: set[AgentId] = set()
    for pattern in (
        r"([SABC,\s]+)(?:无需发言|不用发言|不用回答|不需要回答|跳过|静默|闭嘴)",
        r"(?:不需要|不要|跳过)\s*([SABC,\s]+)",
    ):
        for match in re.finditer(pattern, normalized):
            excluded.update(_extract_agents(match.group(1)))

    if excluded:
        remaining = [agent for agent in all_agents if agent not in excluded]
        return remaining or all_agents

    return all_agents


def router_node(state: CouncilState) -> CouncilState:
    if state.get("active_agents"):
        return {"active_agents": state["active_agents"]}
    return {"active_agents": parse_active_agents(state.get("human_input", ""))}


def _extract_agents(text: str) -> list[AgentId]:
    seen: list[AgentId] = []
    for char in text:
        if char in {"S", "A", "B", "C"} and char not in seen:
            seen.append(char)
    return seen


def _next_active_agent(active_agents: list[AgentId], after: AgentId | None = None) -> str:
    if after is None:
        return {"S": "agent_s", "A": "agent_a", "B": "agent_b", "C": "agent_c"}.get(active_agents[0], END) if active_agents else END

    passed_current = False
    for agent in AGENT_ORDER:
        if agent == after:
            passed_current = True
            continue
        if passed_current and agent in active_agents:
            return {"S": "agent_s", "A": "agent_a", "B": "agent_b", "C": "agent_c"}[agent]
    return END


def _route_after(after: AgentId | None = None) -> Callable[[CouncilState], str]:
    def route(state: CouncilState) -> str:
        active_agents = state.get("active_agents", DEFAULT_ACTIVE_AGENTS)
        next_node = _next_active_agent(active_agents, after=after)
        if next_node == END:
            return "summarizer" if len(state.get("messages", [])) > 10 else END
        return next_node

    return route


def build_graph(
    settings: Settings,
    preset_prompt: str = "",
    team_name: str = "",
    selected_skills: dict[AgentId, str] | None = None,
    prompt_overrides: dict[AgentId, str] | None = None,
):
    configure_agents(
        settings=settings,
        preset_prompt=preset_prompt,
        team_name=team_name,
        selected_skills=selected_skills,
        prompt_overrides=prompt_overrides,
    )

    builder = StateGraph(CouncilState)
    builder.add_node("router", router_node)
    builder.add_node("agent_s", node_agent_s)
    builder.add_node("agent_a", node_agent_a)
    builder.add_node("agent_b", node_agent_b)
    builder.add_node("agent_c", node_agent_c)
    builder.add_node("summarizer", node_summarizer)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        _route_after(),
        {"agent_s": "agent_s", "agent_a": "agent_a", "agent_b": "agent_b", "agent_c": "agent_c", "summarizer": "summarizer", END: END},
    )
    builder.add_conditional_edges(
        "agent_s",
        _route_after(after="S"),
        {"agent_a": "agent_a", "agent_b": "agent_b", "agent_c": "agent_c", "summarizer": "summarizer", END: END},
    )
    builder.add_conditional_edges(
        "agent_a",
        _route_after(after="A"),
        {"agent_b": "agent_b", "agent_c": "agent_c", "summarizer": "summarizer", END: END},
    )
    builder.add_conditional_edges(
        "agent_b",
        _route_after(after="B"),
        {"agent_c": "agent_c", "summarizer": "summarizer", END: END},
    )
    builder.add_conditional_edges(
        "agent_c",
        _route_after(after="C"),
        {"summarizer": "summarizer", END: END},
    )
    builder.add_edge("summarizer", END)

    return builder.compile(checkpointer=MemorySaver())
