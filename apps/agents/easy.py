"""Easy route: one retrieval, one streamed answer."""

from __future__ import annotations

from events import emit
from excerpts import ExcerptPool
from llm import stream_answer
from nodes_common import Deps, context_block, conversation, final_update, search
from state import AgentState

EASY_RESULTS = 5


def make_easy(deps: Deps):
    """Build the ``easy_answer`` node.

    Args:
        deps: Shared node dependencies.

    Returns:
        An async node that retrieves the top passages and streams a cited answer.
    """

    async def easy_answer(state: AgentState) -> dict:
        emit(progress="Searching the document…")
        pool = ExcerptPool()
        excerpts = await search(
            deps, state["knowledge_base_id"], state["question"], EASY_RESULTS, pool
        )
        answer = await stream_answer(
            deps.model,
            deps.prompts["answer"],
            question=state["question"],
            context=context_block(excerpts),
            messages=conversation(state),
        )
        return {"excerpts": pool.items, **final_update(answer)}

    return easy_answer
