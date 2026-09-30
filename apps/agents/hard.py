"""Hard route: decompose, retrieve in parallel, cross-check, then synthesize."""

from __future__ import annotations

import asyncio

from events import emit
from excerpts import ExcerptPool
from llm import ask, stream_answer
from nodes_common import Deps, context_block, conversation, final_update, search
from state import AgentState, Analysis, Decomposition

HARD_RESULTS = 5
MAX_ROUNDS = 2  # the initial retrieval plus at most one gap-filling round


def make_hard(deps: Deps):
    """Build the nodes and branch function of the hard route.

    Args:
        deps: Shared node dependencies.

    Returns:
        ``(decompose, retrieve_many, analyze, synthesize, needs_more)``: four async nodes and
        the conditional-edge function that loops back for one more retrieval round.
    """

    async def decompose(state: AgentState) -> dict:
        emit(progress="Breaking the question into parts…")
        result = await ask(
            deps.model,
            Decomposition,
            deps.prompts["decompose"],
            question=state["question"],
        )
        return {"sub_queries": result.sub_queries}

    async def retrieve_many(state: AgentState) -> dict:
        queries = state["sub_queries"]
        emit(progress=f"Searching the document for {len(queries)} topic(s)…")
        pool = ExcerptPool(state.get("excerpts", []))
        await asyncio.gather(
            *(
                search(deps, state["knowledge_base_id"], query, HARD_RESULTS, pool)
                for query in queries
            )
        )
        return {"excerpts": pool.items, "rounds": state.get("rounds", 0) + 1}

    async def analyze(state: AgentState) -> dict:
        emit(progress="Cross-checking what I found…")
        result = await ask(
            deps.model,
            Analysis,
            deps.prompts["analyze"],
            question=state["question"],
            context=context_block(state["excerpts"]),
        )
        return {
            "notes": result.notes,
            "sub_queries": [] if result.sufficient else result.follow_up_queries,
        }

    async def synthesize(state: AgentState) -> dict:
        answer = await stream_answer(
            deps.model,
            deps.prompts["synthesize"],
            question=state["question"],
            context=context_block(state["excerpts"]),
            notes=state.get("notes", ""),
            messages=conversation(state),
        )
        return final_update(answer)

    def needs_more(state: AgentState) -> str:
        more = bool(state.get("sub_queries")) and state.get("rounds", 0) < MAX_ROUNDS
        return "retrieve_many" if more else "synthesize"

    return decompose, retrieve_many, analyze, synthesize, needs_more
