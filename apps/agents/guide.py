"""Guide route: an orchestrator plans the procedure and subagents extract each part in parallel."""

from __future__ import annotations

from langgraph.types import Send

from events import emit
from excerpts import Excerpt, ExcerptPool, Passage
from llm import ask, stream_answer
from nodes_common import Deps, context_block, conversation, final_update, search
from state import (
    AgentState,
    GuidePlan,
    Prerequisites,
    SectionSpec,
    SectionSteps,
    Step,
)

OVERVIEW_RESULTS = 12
SECTION_RESULTS = 8
PREREQUISITE_RESULTS = 6


def _passages(ids: list[int], excerpts: list[Excerpt]) -> list[Passage]:
    """Map a subagent's local excerpt ids back to the passages they name."""
    by_id = {excerpt["id"]: excerpt for excerpt in excerpts}
    return [
        Passage(
            text=by_id[i]["text"],
            page=by_id[i]["page"],
            source=by_id[i]["source"],
            section=by_id[i]["section"],
        )
        for i in dict.fromkeys(ids)
        if i in by_id
    ]


def _with_passages(
    steps: list[Step], excerpts: list[Excerpt]
) -> list[tuple[str, list[Passage]]]:
    """Keep only the steps a retrieved excerpt actually supports.

    A step whose excerpt ids name nothing the subagent retrieved is model invention, so it is
    dropped. This is the guard that stops a guide from being made up when the document does not
    contain the procedure.
    """
    grounded = []
    for step in steps:
        if passages := _passages(step.excerpt_ids, excerpts):
            grounded.append((step.text, passages))
    return grounded


def render_draft(state: AgentState, pool: ExcerptPool) -> str:
    """Render the subagents' findings as an ordered, globally numbered draft.

    Args:
        state: State carrying the sections and prerequisites the subagents returned.
        pool: Pool that assigns each passage its final citation id.

    Returns:
        A plain-text outline whose ``[[n]]`` markers refer to ``pool``'s excerpts.
    """

    def cite(passages: list[Passage]) -> str:
        return "".join(f" [[{item['id']}]]" for item in pool.add(passages))

    lines: list[str] = []
    if state.get("prerequisites"):
        lines.append("PREREQUISITES")
        lines += [f"- {text}{cite(p)}" for text, p in state["prerequisites"]]
    for section in sorted(state.get("sections", []), key=lambda s: s["index"]):
        if not section["steps"] and not section["warnings"]:
            continue  # nothing grounded for this section; an empty heading would only mislead
        lines += ["", f"SECTION: {section['heading']}"]
        lines += [f"- step: {text}{cite(p)}" for text, p in section["steps"]]
        lines += [f"- warning: {text}{cite(p)}" for text, p in section["warnings"]]
    return "\n".join(lines)


def make_guide(deps: Deps):
    """Build the nodes and fan-out function of the guide route.

    Args:
        deps: Shared node dependencies.

    Returns:
        ``(guide_plan, fan_out, section_extractor, prerequisites_checker, guide_assemble)``.
        ``section_extractor`` and ``prerequisites_checker`` are the subagents that run in
        parallel through ``Send``; ``fan_out`` is the conditional edge that dispatches them.
    """

    async def guide_plan(state: AgentState) -> dict:
        emit(progress="Mapping the document to plan your guide…")
        pool = ExcerptPool()
        overview = await search(
            deps, state["knowledge_base_id"], state["question"], OVERVIEW_RESULTS, pool
        )
        plan = await ask(
            deps.model,
            GuidePlan,
            deps.prompts["guide_plan"],
            question=state["question"],
            context=context_block(overview),
        )
        return {
            "guide_title": plan.title,
            "outline": [s.model_dump() for s in plan.sections],
        }

    def fan_out(state: AgentState) -> list[Send]:
        base = {
            "knowledge_base_id": state["knowledge_base_id"],
            "question": state["question"],
            "guide_title": state.get("guide_title", ""),
        }
        sections = [
            Send("section_extractor", {**base, "index": i, "section": spec})
            for i, spec in enumerate(
                SectionSpec.model_validate(raw) for raw in state["outline"]
            )
        ]
        return [*sections, Send("prerequisites_checker", base)]

    async def section_extractor(task: dict) -> dict:
        spec: SectionSpec = task["section"]
        emit(progress=f"Extracting steps: {spec.heading}…")
        pool = ExcerptPool()
        excerpts = await search(
            deps,
            task["knowledge_base_id"],
            f"{task['question']}: {spec.search_query}",  # keep the search on the requested procedure
            SECTION_RESULTS,
            pool,
        )
        result = await ask(
            deps.model,
            SectionSteps,
            deps.prompts["guide_section"],
            question=task["question"],
            heading=spec.heading,
            context=context_block(excerpts),
        )
        return {
            "sections": [
                {
                    "index": task["index"],
                    "heading": spec.heading,
                    "steps": _with_passages(result.steps, excerpts),
                    "warnings": _with_passages(result.warnings, excerpts),
                }
            ]
        }

    async def prerequisites_checker(task: dict) -> dict:
        emit(progress="Checking prerequisites and materials…")
        pool = ExcerptPool()
        excerpts = await search(
            deps,
            task["knowledge_base_id"],
            f"requirements, tools, materials and preparation before {task['guide_title']}",
            PREREQUISITE_RESULTS,
            pool,
        )
        result = await ask(
            deps.model,
            Prerequisites,
            deps.prompts["guide_prerequisites"],
            question=task["question"],
            context=context_block(excerpts),
        )
        return {"prerequisites": _with_passages(result.items, excerpts)}

    async def guide_assemble(state: AgentState) -> dict:
        emit(progress="Writing the guide…")
        pool = ExcerptPool()
        draft = render_draft(state, pool)
        answer = await stream_answer(
            deps.model,
            deps.prompts["guide_assemble"],
            question=state["question"],
            title=state.get("guide_title", ""),
            draft=draft or "(the document contained no usable steps for this request)",
            messages=conversation(state),
        )
        return {"excerpts": pool.items, **final_update(answer)}

    return guide_plan, fan_out, section_extractor, prerequisites_checker, guide_assemble
