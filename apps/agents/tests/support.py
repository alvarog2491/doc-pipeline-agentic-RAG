"""Test doubles for the orchestrator: a scripted chat model, a canned retriever, real prompts."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from langchain_core.messages import AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from excerpts import Passage
from nodes_common import PROMPT_NAMES

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompts() -> dict[str, ChatPromptTemplate]:
    """Load the repo's real prompt YAML the way Langfuse would render it."""
    prompts = {}
    for name in PROMPT_NAMES:
        doc = yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text())
        messages = []
        for message in doc["messages"]:
            if "placeholder" in message:
                messages.append(
                    MessagesPlaceholder(message["placeholder"], optional=True)
                )
            else:
                text = re.sub(r"\{\{(\w+)\}\}", r"{\1}", message["content"])
                messages.append((message["role"], text))
        prompts[name] = ChatPromptTemplate.from_messages(messages)
    return prompts


class _Structured:
    def __init__(self, model: FakeModel, schema: type) -> None:
        self._model, self._schema = model, schema

    async def ainvoke(self, messages):
        self._model.calls.append((self._schema.__name__, messages))
        queue = self._model.structured[self._schema]
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(result, Exception):
            raise result
        return result


class FakeModel:
    """Chat model returning scripted structured outputs and streamed texts."""

    def __init__(self, structured: dict | None = None, texts: list[str] | None = None):
        self.structured = structured or {}
        self.texts = list(texts or [])
        self.calls: list[tuple[str, list]] = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)

    async def astream(self, messages):
        self.calls.append(("stream", messages))
        for word in self.texts.pop(0).split(" "):
            yield AIMessageChunk(content=word + " ")

    def prompts_for(self, name: str) -> list:
        return [messages for label, messages in self.calls if label == name]


class FakeRetriever:
    """Returns passages keyed by query substring and records every call."""

    def __init__(self, by_query: dict[str, list[Passage]] | None = None):
        self.by_query = by_query or {}
        self.calls: list[tuple[str, str, int]] = []

    async def __call__(self, knowledge_base_id: str, query: str, limit: int):
        self.calls.append((knowledge_base_id, query, limit))
        for needle, passages in self.by_query.items():
            if needle in query:
                return passages
        return []


def passage(text: str, page: int = 1, section: str = "") -> Passage:
    return Passage(text=text, page=page, source="uploads/manual.pdf", section=section)
