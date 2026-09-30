import graph_diagram


def test_the_readme_diagram_is_the_one_langgraph_draws_for_the_compiled_graph():
    assert graph_diagram.readme_block() == graph_diagram.mermaid(), (
        "README.md is stale: run `uv run --package DocPipelineAgent python graph_diagram.py --write`"
    )


def test_the_drawn_graph_contains_every_workflow_edge():
    source = graph_diagram.mermaid()

    for edge in (
        "classify -. &nbsp;easy&nbsp; .-> easy_answer",
        "classify -. &nbsp;hard&nbsp; .-> decompose",
        "classify -. &nbsp;guide&nbsp; .-> guide_plan",
        "analyze -. &nbsp;gaps&nbsp; .-> retrieve_many",
        "analyze -. &nbsp;enough&nbsp; .-> synthesize",
        "guide_plan -.-> section_extractor",
        "guide_plan -.-> prerequisites_checker",
        "section_extractor --> guide_assemble",
        "prerequisites_checker --> guide_assemble",
    ):
        assert edge in source, edge
