"""Publish user-facing events from graph nodes onto the LangGraph custom stream.

Everything the client sees flows through this one channel, so internal model calls (the
router, planners, extractors) never leak into the answer stream.
"""

from langgraph.config import get_stream_writer


def emit(**event: object) -> None:
    """Publish one event to the graph's custom stream.

    Args:
        **event: Event payload, for example ``chunk="text"``, ``progress="Searching…"`` or
            ``route="easy"``.
    """
    try:
        get_stream_writer()(event)
    except (RuntimeError, KeyError):
        pass  # called outside a streamed graph run, such as a direct node unit test
