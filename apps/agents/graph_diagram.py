"""Draw the orchestrator with LangGraph's own renderer and keep the README's copy in sync.

    uv run --package DocPipelineAgent python graph_diagram.py           # print the Mermaid source
    uv run --package DocPipelineAgent python graph_diagram.py --write   # refresh README.md

The diagram comes from ``get_graph().draw_mermaid()`` on the compiled graph, so it cannot drift
from ``graph.py``: a test fails when the README block differs from what this module produces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, cast

from graph import build_agent

README = Path(__file__).with_name("README.md")
START, END = "<!-- graph:start -->", "<!-- graph:end -->"
_BLOCK = re.compile(
    rf"{re.escape(START)}\n```mermaid\n(.*?)\n```\n{re.escape(END)}", re.DOTALL
)


def mermaid() -> str:
    """Return the compiled orchestrator graph as LangGraph's official Mermaid source.

    Compiling needs no model, retriever or prompts, so stubs are enough to draw the topology.
    """
    agent = build_agent(model=cast(Any, None), retrieve=cast(Any, None), prompts={})
    return agent.get_graph().draw_mermaid().strip()


def readme_block() -> str:
    """Return the Mermaid source currently embedded in the README."""
    match = _BLOCK.search(README.read_text())
    if match is None:
        raise ValueError(f"README.md has no {START} ... {END} block")
    return match.group(1)


def write_readme() -> None:
    """Replace the README's embedded diagram with the freshly generated one."""
    block = f"{START}\n```mermaid\n{mermaid()}\n```\n{END}"
    README.write_text(_BLOCK.sub(lambda _: block, README.read_text()))


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_readme()
    else:
        print(mermaid())
