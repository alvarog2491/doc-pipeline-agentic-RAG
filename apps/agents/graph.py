"""Assemble the orchestrator graph: classify, then route to the easy, hard or guide workflow.

::

    START -> classify -+-> easy_answer ------------------------------> END
                       |
                       +-> decompose -> retrieve_many -> analyze -+-> synthesize -> END
                       |                       ^                  |
                       |                       +---- gaps found --+
                       |
                       +-> guide_plan -> [section_extractor x N, prerequisites_checker]
                                                   -> guide_assemble -> END

Every user-visible token, progress line and route event is published through
``events.emit`` so internal model calls never reach the client.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from easy import make_easy
from guide import make_guide
from hard import make_hard
from nodes_common import Deps
from retrieval import Retriever
from router import make_router
from state import AgentState

# Top-level agent name every graph run reports to Langfuse (main.py).
AGENT_NAME = "DocPipeline-Orchestrator"
GRAPH_TRACE_NAME = "DocPipeline-Agent-Graph"


def build_agent(
    *,
    model: BaseChatModel,
    router_model: BaseChatModel | None = None,
    retrieve: Retriever,
    prompts: dict[str, ChatPromptTemplate],
):
    """Compile the orchestrator graph.

    Args:
        model: Chat model for reasoning and answers.
        router_model: Model for the classification step; defaults to ``model``.
        retrieve: Knowledge Base search function.
        prompts: Chat prompts keyed by ``nodes_common.PROMPT_NAMES``.

    Returns:
        A compiled graph with in-memory conversational checkpoints keyed by ``thread_id``.
    """
    deps = Deps(
        model=model,
        router_model=router_model or model,
        retrieve=retrieve,
        prompts=prompts,
    )
    decompose, retrieve_many, analyze, synthesize, needs_more = make_hard(deps)
    guide_plan, fan_out, section_extractor, prerequisites_checker, guide_assemble = (
        make_guide(deps)
    )

    graph = StateGraph(AgentState)
    graph.add_node("classify", make_router(deps))
    graph.add_node("easy_answer", make_easy(deps))
    graph.add_node("decompose", decompose)
    graph.add_node("retrieve_many", retrieve_many)
    graph.add_node("analyze", analyze)
    graph.add_node("synthesize", synthesize)
    graph.add_node("guide_plan", guide_plan)
    graph.add_node("section_extractor", section_extractor)
    graph.add_node("prerequisites_checker", prerequisites_checker)
    graph.add_node("guide_assemble", guide_assemble)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        lambda state: state["route"],
        {"easy": "easy_answer", "hard": "decompose", "guide": "guide_plan"},
    )
    graph.add_edge("easy_answer", END)
    graph.add_edge("decompose", "retrieve_many")
    graph.add_edge("retrieve_many", "analyze")
    graph.add_conditional_edges(
        "analyze", needs_more, {"gaps": "retrieve_many", "enough": "synthesize"}
    )
    graph.add_edge("synthesize", END)
    graph.add_conditional_edges(
        "guide_plan", fan_out, ["section_extractor", "prerequisites_checker"]
    )
    graph.add_edge("section_extractor", "guide_assemble")
    graph.add_edge("prerequisites_checker", "guide_assemble")
    graph.add_edge("guide_assemble", END)

    return graph.compile(checkpointer=InMemorySaver(), name=AGENT_NAME)
