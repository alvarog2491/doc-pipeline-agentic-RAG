"""Classify each turn as an easy question, a hard question, or a step-by-step guide request."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from events import emit
from llm import ask
from nodes_common import Deps, history
from state import RESET, AgentState, RouteDecision

logger = logging.getLogger(__name__)

_FALLBACK_ROUTE = "hard"  # the safest default: reason more rather than answer shallowly
_RECENT_MESSAGES = 6


def _latest_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def make_router(deps: Deps):
    """Build the ``classify`` node.

    Args:
        deps: Shared node dependencies.

    Returns:
        An async graph node that sets ``route`` and a standalone ``question`` and resets
        every per-turn field.
    """

    async def classify(state: AgentState) -> dict:
        latest = _latest_user_text(state)
        recent = history(state)[-_RECENT_MESSAGES:]
        try:
            decision = await ask(
                deps.router_model,
                RouteDecision,
                deps.prompts["router"],
                messages=recent,
            )
            route, question = decision.route, decision.standalone_question or latest
        except Exception:
            logger.exception(
                "Router failed; falling back to the %s route", _FALLBACK_ROUTE
            )
            route, question = _FALLBACK_ROUTE, latest
        emit(route=route)
        return {
            "route": route,
            "question": question,
            "excerpts": [],
            "sub_queries": [],
            "notes": "",
            "rounds": 0,
            "guide_title": "",
            "outline": [],
            "sections": [RESET],
            "prerequisites": [RESET],
            "answer": "",
        }

    return classify
