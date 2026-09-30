"""Propagate standard distributed trace context into Langfuse observations."""

import re
from collections.abc import Mapping

_TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}")


def trace_context_from_headers(headers: object) -> dict[str, str] | None:
    """Extract a valid W3C trace parent without affecting request handling.

    Args:
        headers: Incoming request headers, potentially with mixed-case names.

    Returns:
        Langfuse trace context when ``traceparent`` is valid, otherwise ``None``.
    """
    if not isinstance(headers, Mapping):
        return None
    normalized = {str(key).lower(): value for key, value in headers.items()}
    traceparent = normalized.get("traceparent")
    match = (
        _TRACEPARENT.fullmatch(traceparent) if isinstance(traceparent, str) else None
    )
    if match is None or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
        return None
    return {"trace_id": match.group(1), "parent_span_id": match.group(2)}
