"""Load and render the Langfuse-hosted agent prompts."""

import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from langchain_core.prompts import ChatPromptTemplate
from langfuse import get_client

# One label per environment prevents environments sharing a Langfuse project from reading
# each other's prompt versions. Local runs default to the development label.
DEFAULT_PROMPT_LABEL = "dev"


def load_chat_prompt(name: str) -> ChatPromptTemplate:
    """Load an environment-specific Langfuse chat prompt.

    Args:
        name: Langfuse prompt name.

    Returns:
        A chat prompt template carrying Langfuse tracing metadata.
    """
    prompt = get_client().get_prompt(
        name=name,
        type="chat",
        label=prompt_label(),
    )
    return ChatPromptTemplate(
        prompt.get_langchain_prompt(),
        metadata={"langfuse_prompt": prompt},
    )


def load_chat_prompts(names: Sequence[str]) -> dict[str, ChatPromptTemplate]:
    """Load multiple Langfuse chat prompts concurrently.

    Args:
        names: Prompt names to fetch.

    Returns:
        Prompt templates keyed by name, preserving input order and tracing metadata.
    """
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=len(names)) as executor:
        return dict(zip(names, executor.map(load_chat_prompt, names), strict=True))


def system_text(prompt: ChatPromptTemplate, **values: str) -> str:
    """Render the system message from a chat prompt.

    Args:
        prompt: Chat prompt whose first message contains the system template.
        **values: Values for declared template variables. Missing variables render as empty
            strings.

    Returns:
        The formatted system-message text.
    """
    template = prompt.messages[0].prompt
    return template.format(
        **{name: values.get(name, "") for name in template.input_variables}
    )


def prompt_label() -> str:
    """Return the active Langfuse prompt label.

    Returns:
        The trimmed ``PROMPT_LABEL`` value, or the development label when unset or blank.
    """
    return os.environ.get("PROMPT_LABEL", "").strip() or DEFAULT_PROMPT_LABEL
