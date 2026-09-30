"""Graph state and the structured outputs each node asks the model for."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from excerpts import Excerpt, Passage

Route = Literal["easy", "hard", "guide"]


class RouteDecision(BaseModel):
    """The router's verdict on one user turn."""

    route: Route = Field(
        description=(
            "easy: one fact or short explanation found in a single place. "
            "hard: needs comparing, combining or reasoning across several parts. "
            "guide: the user wants a complete step-by-step procedure."
        )
    )
    standalone_question: str = Field(
        description="The user's request rewritten so it makes sense without the chat history."
    )
    reason: str = Field(description="One short sentence justifying the route.")


class Decomposition(BaseModel):
    """Sub-questions that together answer a hard question."""

    sub_queries: list[str] = Field(
        min_length=1, max_length=4, description="Self-contained search queries."
    )


class Analysis(BaseModel):
    """A sufficiency check over the excerpts retrieved so far."""

    sufficient: bool = Field(
        description="True when the excerpts can answer the question."
    )
    notes: str = Field(
        description="Key facts, how they relate, contradictions, and what is still missing."
    )
    follow_up_queries: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Searches that would fill the gaps; empty when sufficient.",
    )


class SectionSpec(BaseModel):
    """One part of a procedure to extract in detail."""

    heading: str
    search_query: str = Field(
        description="What to search for to find this part's steps."
    )


class GuidePlan(BaseModel):
    """The outline of a step-by-step guide."""

    title: str
    sections: list[SectionSpec] = Field(min_length=1, max_length=6)


class Step(BaseModel):
    """One instruction and the excerpts that support it."""

    text: str
    excerpt_ids: list[int] = Field(default_factory=list)


class SectionSteps(BaseModel):
    """Ordered steps and warnings extracted for one section."""

    steps: list[Step] = Field(default_factory=list)
    warnings: list[Step] = Field(default_factory=list)


class Prerequisites(BaseModel):
    """Requirements to check before starting a procedure."""

    items: list[Step] = Field(default_factory=list)


class SectionResult(TypedDict):
    """A subagent's extracted section, carrying its own passages for later numbering."""

    index: int
    heading: str
    steps: list[tuple[str, list[Passage]]]
    warnings: list[tuple[str, list[Passage]]]


RESET = "__reset__"


def accumulate(left: list | None, right: list) -> list:
    """Append parallel subagent results, or clear the list when ``right`` starts with ``RESET``.

    Args:
        left: Results gathered so far this turn.
        right: New results from one subagent, or ``[RESET]`` from the router.

    Returns:
        The combined list.
    """
    if right and right[0] == RESET:
        return list(right[1:])
    return [*(left or []), *right]


class AgentState(TypedDict, total=False):
    """State of one conversation thread.

    Per-turn fields (everything except ``messages``) are reset by the router node.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    knowledge_base_id: str
    question: str
    route: Route
    sub_queries: list[str]
    excerpts: list[Excerpt]
    notes: str
    rounds: int
    guide_title: str
    outline: list[dict]
    sections: Annotated[list[SectionResult], accumulate]
    prerequisites: Annotated[list[tuple[str, list[Passage]]], accumulate]
    answer: str
