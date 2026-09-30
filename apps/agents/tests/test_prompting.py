"""Test Langfuse prompt loading and rendering."""

from threading import Barrier

from langchain_core.prompts import ChatPromptTemplate

import prompting


def test_load_chat_prompts_fetches_cold_prompts_concurrently(monkeypatch):
    both_fetches_started = Barrier(2)

    def load(name):
        both_fetches_started.wait(timeout=1)
        return ChatPromptTemplate.from_messages([("system", name)])

    monkeypatch.setattr(prompting, "load_chat_prompt", load)

    prompts = prompting.load_chat_prompts(names=("first", "second"))

    assert set(prompts) == {"first", "second"}


def test_prompt_label_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("PROMPT_LABEL", raising=False)

    assert prompting.prompt_label() == prompting.DEFAULT_PROMPT_LABEL


def test_prompt_label_reads_the_environment(monkeypatch):
    monkeypatch.setenv("PROMPT_LABEL", "staging")

    assert prompting.prompt_label() == "staging"


def test_blank_prompt_label_falls_back_rather_than_querying_for_an_empty_label(
    monkeypatch,
):
    monkeypatch.setenv("PROMPT_LABEL", "   ")

    assert prompting.prompt_label() == prompting.DEFAULT_PROMPT_LABEL


def test_load_chat_prompt_fetches_this_environments_label(monkeypatch):
    requested = {}

    class StubPrompt:
        def get_langchain_prompt(self):
            return [("system", "stub"), ("placeholder", "{messages}")]

    class StubClient:
        def get_prompt(self, name, *, type, label):
            requested["name"], requested["label"] = name, label
            return StubPrompt()

    monkeypatch.setenv("PROMPT_LABEL", "prod")
    monkeypatch.setattr(prompting, "get_client", StubClient)

    prompting.load_chat_prompt(name="router")

    assert requested == {"name": "router", "label": "prod"}
