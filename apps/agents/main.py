"""Expose the AgentCore runtime entrypoint for chat and feedback requests."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping

from dotenv import load_dotenv

load_dotenv()

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage
from langfuse import propagate_attributes
from langfuse.langchain import CallbackHandler

from citations import resolve_citations
from graph import AGENT_NAME, GRAPH_TRACE_NAME, build_agent
from langfuse_client import init_langfuse_client
from model.load import load_model
from nodes_common import PROMPT_NAMES
from observability import trace_context_from_headers
from prompting import load_chat_prompts
from retrieval import KNOWLEDGE_BASE_ID, RETRIEVAL_LOG, retrieve

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()
langfuse = init_langfuse_client()

_agent = None


def get_agent():
    """Return the process-wide orchestrator graph, building it on first use.

    Returns:
        The cached compiled graph.
    """
    global _agent
    if _agent is None:
        logger.info("Building agent")
        model = load_model()
        router_model = load_model("BEDROCK_ROUTER_MODEL_ID") if _has_router() else model
        _agent = build_agent(
            model=model,
            router_model=router_model,
            retrieve=retrieve,
            prompts=load_chat_prompts(names=PROMPT_NAMES),
        )
    return _agent


def _has_router() -> bool:
    return bool(os.environ.get("BEDROCK_ROUTER_MODEL_ID"))


async def _run(
    prompt: str,
    knowledge_base_id: str,
    session_id: str,
    *,
    trace_context: dict[str, str] | None = None,
    diagnostics: bool = False,
) -> AsyncIterator[dict]:
    """Stream one graph run as route, progress, answer-chunk and citation events.

    When ``diagnostics`` is set, a final ``{"diagnostics": ...}`` event reports the route,
    retrieval count, retrieved excerpts and subagent output counts for the evaluation suite.
    """
    logger.info("Running graph for session_id=%s", session_id)
    with (
        langfuse.start_as_current_observation(
            trace_context=trace_context,
            name=AGENT_NAME,
            as_type="agent",
            input=prompt,
            metadata={"knowledge_base_id": knowledge_base_id},
        ) as agent_span,
        propagate_attributes(trace_name=GRAPH_TRACE_NAME, session_id=session_id),
    ):
        agent = get_agent()
        config = {
            "configurable": {"thread_id": f"{session_id}:{knowledge_base_id}"},
            "callbacks": [CallbackHandler()],
        }
        inputs = {
            "messages": [HumanMessage(content=prompt)],
            "knowledge_base_id": knowledge_base_id,
        }
        answer_chunks: list[str] = []
        route = ""
        retrieval_log: list[dict] = []
        RETRIEVAL_LOG.set(retrieval_log)

        async for event in agent.astream(inputs, config=config, stream_mode="custom"):
            if not isinstance(event, Mapping):
                continue
            if chunk := event.get("chunk"):
                answer_chunks.append(chunk)
            elif event.get("route"):
                route = event["route"]
            yield dict(event)

        answer = "".join(answer_chunks)
        values = (await agent.aget_state(config)).values
        excerpts = values.get("excerpts", [])
        citations = resolve_citations(answer, excerpts)
        yield {"citations": citations}
        if diagnostics:
            yield {
                "diagnostics": {
                    "route": route,
                    "retrievals": len(retrieval_log),
                    "retrieved": [
                        {"id": e["id"], "page": e["page"], "source": e["source"]}
                        for e in excerpts
                    ],
                    "sections": len(values.get("sections", [])),
                    "prerequisites": len(values.get("prerequisites", [])),
                }
            }
        agent_span.update(
            output=answer,
            metadata={
                "route": route,
                "retrieved": [
                    {"id": e["id"], "page": e["page"], "source": e["source"]}
                    for e in excerpts
                ],
                "citations": citations,
            },
        )
        logger.info(
            "Agent run complete for session_id=%s route=%s chunks=%d",
            session_id,
            route,
            len(answer_chunks),
        )


# Langfuse score name for the end-of-conversation "was this helpful?" signal. One consistent
# name so the categorical scores aggregate in the Langfuse Sessions view.
FEEDBACK_SCORE_NAME = "user_feedback"

_VALID_OUTCOMES = ("helpful", "not_helpful")


def _record_feedback(payload: Mapping[str, object], session_id: str) -> dict[str, str]:
    """Record the user's feedback on a conversation in Langfuse.

    Args:
        payload: Feedback request containing an outcome and optional comment.
        session_id: AgentCore session associated with the conversation.

    Returns:
        A status mapping confirming that the score was recorded.
    """
    outcome = str(payload.get("outcome") or "").strip()
    if outcome not in _VALID_OUTCOMES:
        logger.warning(
            "Unexpected feedback outcome %r for session_id=%s; recording as-is",
            outcome,
            session_id,
        )
    comment = str(payload.get("comment") or "").strip() or None

    langfuse.create_score(
        name=FEEDBACK_SCORE_NAME,
        value=outcome,
        session_id=session_id,
        data_type="CATEGORICAL",
        comment=comment,
    )
    # The runtime may be frozen right after the response, so flush eagerly.
    langfuse.flush()
    logger.info(
        "Recorded %s=%s for session_id=%s", FEEDBACK_SCORE_NAME, outcome, session_id
    )
    return {"status": "ok"}


def _chat_prompt(payload: Mapping[str, object]) -> str:
    """Return the validated chat prompt from a runtime payload."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("payload.prompt must be a non-empty string")
    return prompt


def _knowledge_base_id(payload: Mapping[str, object]) -> str:
    """Return the validated Knowledge Base id from a runtime payload."""
    value = payload.get("knowledgeBaseId")
    if not isinstance(value, str) or not KNOWLEDGE_BASE_ID.fullmatch(value):
        raise ValueError("payload.knowledgeBaseId must be a Bedrock Knowledge Base id")
    return value


def _session_id(context: object) -> str:
    """Return the validated AgentCore session identifier."""
    session_id = getattr(context, "session_id", None)
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("AgentCore context must contain a non-empty session ID")
    return session_id


@app.entrypoint
async def invoke(payload: object, context: object) -> AsyncIterator[dict]:
    """Handles an AgentCore chat or feedback invocation.

    Invoke this runtime entrypoint for every Gateway request. Chat payloads stream
    ``route``, ``progress``, ``chunk`` and final ``citations`` events; feedback payloads emit
    one acknowledgement after recording the session score.

    Args:
        payload: Request mapping with ``prompt`` and ``knowledgeBaseId`` for chat (plus an
            optional ``diagnostics: true`` used only by the evaluation suite), or
            ``type: "feedback"`` with an ``outcome``.
        context: AgentCore invocation context carrying the runtime session identifier.

    Yields:
        Event mappings for chat requests or a feedback acknowledgement mapping.

    Raises:
        TypeError: If the runtime payload is not a mapping.
        ValueError: If the session identifier is missing, the prompt is not a non-empty
            string, or the Knowledge Base id is malformed.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("runtime payload must be a mapping")

    session_id = _session_id(context)

    if payload.get("type") == "feedback":
        logger.info("Feedback received for session_id=%s", session_id)
        yield _record_feedback(payload, session_id)
        return

    prompt = _chat_prompt(payload)
    knowledge_base_id = _knowledge_base_id(payload)
    trace_context = trace_context_from_headers(
        getattr(context, "request_headers", None)
    )

    async for event in _run(
        prompt,
        knowledge_base_id,
        session_id,
        trace_context=trace_context,
        diagnostics=payload.get("diagnostics") is True,
    ):
        yield event

    # The enclosing agent observation ends only once `_run` is exhausted. Flush afterward
    # so every CallbackHandler child is queryable before the AgentCore microVM can freeze.
    await asyncio.to_thread(langfuse.flush)


if __name__ == "__main__":
    app.run()
