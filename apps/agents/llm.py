"""Small helpers for calling the chat model from graph nodes."""

from __future__ import annotations

from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from events import emit

T = TypeVar("T", bound=BaseModel)


def render(prompt: ChatPromptTemplate, **values: object) -> list[BaseMessage]:
    """Render a chat prompt, defaulting the history placeholder to empty."""
    values.setdefault("messages", [])
    return prompt.format_messages(**values)


def chunk_text(content: object) -> str:
    """Return the plain text of a streamed model chunk.

    Args:
        content: ``AIMessageChunk.content``: a string or a list of content blocks.

    Returns:
        The concatenated text, ignoring reasoning and tool-use blocks.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def ask(
    model: BaseChatModel, schema: type[T], prompt: ChatPromptTemplate, **values: object
) -> T:
    """Call the model for a structured answer.

    Args:
        model: Chat model.
        schema: Pydantic class describing the answer.
        prompt: Chat prompt to render.
        **values: Prompt variables.

    Returns:
        The parsed structured output.
    """
    return await model.with_structured_output(schema).ainvoke(render(prompt, **values))


async def stream_answer(
    model: BaseChatModel, prompt: ChatPromptTemplate, **values: object
) -> str:
    """Stream the model's reply to the client as it is generated.

    Args:
        model: Chat model.
        prompt: Chat prompt to render.
        **values: Prompt variables.

    Returns:
        The full reply text.
    """
    parts: list[str] = []
    async for chunk in model.astream(render(prompt, **values)):
        if text := chunk_text(chunk.content):
            parts.append(text)
            emit(chunk=text)
    return "".join(parts)
