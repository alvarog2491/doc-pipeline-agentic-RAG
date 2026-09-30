"""Dependencies and small helpers shared by every graph node."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from excerpts import Excerpt, ExcerptPool, Passage, render_excerpts
from retrieval import Retriever
from state import AgentState

PROMPT_NAMES = (
    "router",
    "answer",
    "decompose",
    "analyze",
    "synthesize",
    "guide_plan",
    "guide_section",
    "guide_prerequisites",
    "guide_assemble",
)

NO_EXCERPTS = "(no matching excerpts were found in the document)"


@dataclass(frozen=True)
class Deps:
    """Everything a node needs from the outside world.

    Attributes:
        model: Chat model for reasoning and answer generation.
        router_model: Cheaper model used only to classify the request.
        retrieve: Knowledge Base search function.
        prompts: Chat prompts keyed by ``PROMPT_NAMES``.
    """

    model: BaseChatModel
    router_model: BaseChatModel
    retrieve: Retriever
    prompts: dict[str, ChatPromptTemplate]


def history(state: AgentState, *, drop_last: bool = False) -> list:
    """Return the conversation so far as chat messages.

    Args:
        state: Current graph state.
        drop_last: Exclude the latest user message (it is passed separately as the question).
    """
    messages = list(state.get("messages", []))
    return messages[:-1] if drop_last and messages else messages


def conversation(state: AgentState) -> list:
    """Return the chat turns for an answer prompt: earlier history, then the current question.

    The current question always closes the list as a user message. A prompt that carries the
    question only inside its system text leaves the model with no user turn, and it answers
    generically instead of using the excerpts.

    Args:
        state: Current graph state; ``question`` is the standalone rewrite of the latest turn.

    Returns:
        Earlier messages without the latest user message, followed by the standalone question.
    """
    return [*history(state, drop_last=True), HumanMessage(content=state["question"])]


def context_block(excerpts: list[Excerpt]) -> str:
    """Render the numbered excerpts, or a marker saying nothing matched."""
    return render_excerpts(excerpts) or NO_EXCERPTS


def final_update(answer: str) -> dict:
    """Return the state update that records the streamed answer."""
    return {"answer": answer, "messages": [AIMessage(content=answer)]}


async def search(
    deps: Deps, knowledge_base_id: str, query: str, limit: int, pool: ExcerptPool
) -> list[Excerpt]:
    """Retrieve passages and number them in ``pool``."""
    passages: list[Passage] = await deps.retrieve(knowledge_base_id, query, limit)
    return pool.add(passages)
