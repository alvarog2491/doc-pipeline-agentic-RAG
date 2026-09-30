"""Every shipped prompt renders with exactly the variables its node supplies."""

import pytest

from nodes_common import PROMPT_NAMES
from tests.support import load_prompts

VARIABLES = {
    "router": set(),
    "answer": {"question", "context"},
    "decompose": {"question"},
    "analyze": {"question", "context"},
    "synthesize": {"question", "context", "notes"},
    "guide_plan": {"question", "context"},
    "guide_section": {"question", "heading", "context"},
    "guide_prerequisites": {"question", "context"},
    "guide_assemble": {"question", "title", "draft"},
}


def test_every_prompt_name_has_a_declared_variable_set():
    assert set(VARIABLES) == set(PROMPT_NAMES)


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_prompt_uses_only_supplied_variables(name):
    prompt = load_prompts()[name]

    assert set(prompt.input_variables) - {"messages"} <= VARIABLES[name]
    values = {variable: "x" for variable in VARIABLES[name]}
    assert prompt.format_messages(**values, messages=[])
