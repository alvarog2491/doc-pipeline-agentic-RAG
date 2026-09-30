"""Test the orchestrator's three routes end to end with scripted models."""

import pytest

from graph import build_agent
from state import (
    Analysis,
    Decomposition,
    GuidePlan,
    Prerequisites,
    RouteDecision,
    SectionSpec,
    SectionSteps,
    Step,
)
from tests.support import FakeModel, FakeRetriever, load_prompts, passage

KB = "ABCDE12345"


def _config(thread="t1"):
    return {"configurable": {"thread_id": thread}}


async def _run(agent, prompt, thread="t1"):
    events = []
    inputs = {"messages": [("user", prompt)], "knowledge_base_id": KB}
    async for event in agent.astream(
        inputs, config=_config(thread), stream_mode="custom"
    ):
        events.append(event)
    state = (await agent.aget_state(_config(thread))).values
    return events, state


def _agent(router, model, retriever):
    return build_agent(
        model=model, router_model=router, retrieve=retriever, prompts=load_prompts()
    )


def _decision(route, question="standalone?"):
    return RouteDecision(route=route, standalone_question=question, reason="because")


def _text(events):
    return "".join(e["chunk"] for e in events if "chunk" in e)


async def test_easy_route_retrieves_once_and_streams_a_cited_answer():
    router = FakeModel(
        {RouteDecision: [_decision("easy", "What is the max pressure?")]}
    )
    model = FakeModel(texts=["The maximum pressure is 3 bar [[1]]."])
    retriever = FakeRetriever({"pressure": [passage("Max pressure 3 bar.", page=4)]})

    events, state = await _run(_agent(router, model, retriever), "and the pressure?")

    assert events[0] == {"route": "easy"}
    assert {"progress": "Searching the document…"} in events
    assert _text(events).strip() == "The maximum pressure is 3 bar [[1]]."
    assert retriever.calls == [(KB, "What is the max pressure?", 5)]
    assert [c[0] for c in model.calls] == ["stream"]
    assert state["excerpts"][0]["page"] == 4
    assert (
        state["messages"][-1].content.strip() == "The maximum pressure is 3 bar [[1]]."
    )


async def test_easy_route_streams_word_by_word_before_the_run_finishes():
    router = FakeModel({RouteDecision: [_decision("easy")]})
    model = FakeModel(texts=["one two three"])

    events, _ = await _run(_agent(router, model, FakeRetriever()), "hi")

    assert [e["chunk"] for e in events if "chunk" in e] == ["one ", "two ", "three "]


async def test_router_failure_falls_back_to_the_hard_route():
    router = FakeModel({RouteDecision: [RuntimeError("bedrock throttled")]})
    model = FakeModel(
        {
            Decomposition: [Decomposition(sub_queries=["a"])],
            Analysis: [Analysis(sufficient=True, notes="n")],
        },
        texts=["done"],
    )

    events, _ = await _run(_agent(router, model, FakeRetriever()), "compare x and y")

    assert events[0] == {"route": "hard"}


async def test_hard_route_decomposes_searches_in_parallel_and_fills_gaps_once():
    router = FakeModel({RouteDecision: [_decision("hard", "Compare A and B")]})
    model = FakeModel(
        {
            Decomposition: [Decomposition(sub_queries=["about A", "about B"])],
            Analysis: [
                Analysis(
                    sufficient=False, notes="need C", follow_up_queries=["about C"]
                ),
                Analysis(
                    sufficient=False,
                    notes="still need D",
                    follow_up_queries=["about D"],
                ),
            ],
        },
        texts=["A differs from B [[1]][[2]]."],
    )
    retriever = FakeRetriever(
        {
            "about A": [passage("A facts", 1)],
            "about B": [passage("B facts", 2)],
            "about C": [passage("C facts", 3)],
        }
    )

    events, state = await _run(_agent(router, model, retriever), "Compare A and B")

    queries = [call[1] for call in retriever.calls]
    assert sorted(queries[:2]) == ["about A", "about B"]
    assert queries[2] == "about C"
    assert "about D" not in queries  # the loop stops after one gap-filling round
    assert state["rounds"] == 2
    assert [e["id"] for e in state["excerpts"]] == [1, 2, 3]
    assert _text(events).startswith("A differs from B")
    progress = [e["progress"] for e in events if "progress" in e]
    assert progress[0] == "Breaking the question into parts…"


async def test_hard_route_skips_the_second_round_when_evidence_is_sufficient():
    router = FakeModel({RouteDecision: [_decision("hard")]})
    model = FakeModel(
        {
            Decomposition: [Decomposition(sub_queries=["q"])],
            Analysis: [Analysis(sufficient=True, notes="fine")],
        },
        texts=["ok"],
    )
    retriever = FakeRetriever({"q": [passage("x")]})

    _, state = await _run(_agent(router, model, retriever), "hard one")

    assert len(retriever.calls) == 1 and state["rounds"] == 1
    synth_prompt = model.prompts_for("stream")[0]
    assert "fine" in synth_prompt[0].content


def _guide_model():
    plan = GuidePlan(
        title="Install the unit",
        sections=[
            SectionSpec(heading="Prepare", search_query="prepare site"),
            SectionSpec(heading="Mount", search_query="mount unit"),
        ],
    )
    return FakeModel(
        {
            GuidePlan: [plan],
            SectionSteps: [
                SectionSteps(
                    steps=[Step(text="Clear the area", excerpt_ids=[1])],
                    warnings=[Step(text="Disconnect power", excerpt_ids=[1])],
                ),
                SectionSteps(steps=[Step(text="Bolt it down", excerpt_ids=[1, 99])]),
            ],
            Prerequisites: [
                Prerequisites(items=[Step(text="A wrench", excerpt_ids=[1])])
            ],
        },
        texts=["# Install the unit"],
    )


async def test_guide_route_fans_out_subagents_and_assembles_an_ordered_cited_draft():
    router = FakeModel({RouteDecision: [_decision("guide", "How do I install it?")]})
    model = _guide_model()
    retriever = FakeRetriever(
        {
            "prepare site": [passage("Clear space.", 2)],
            "mount unit": [passage("Mount with bolts.", 5)],
            "requirements": [passage("You need a wrench.", 1)],
            "install": [passage("Overview.", 1)],
        }
    )

    events, state = await _run(_agent(router, model, retriever), "step by step install")

    asked = {call[1] for call in retriever.calls}
    assert any(
        q.endswith("prepare site") and "How do I install it?" in q for q in asked
    )
    assert any(q.endswith("mount unit") for q in asked)
    assert any(q.startswith("requirements, tools") for q in asked)
    assert len(model.prompts_for("SectionSteps")) == 2
    assert len(model.prompts_for("Prerequisites")) == 1
    draft = model.prompts_for("stream")[0][0].content
    assert (
        draft.index("PREREQUISITES")
        < draft.index("SECTION: Prepare")
        < draft.index("SECTION: Mount")
    )
    assert "- step: Clear the area [[" in draft
    assert "[[99]]" not in draft  # ids the subagent invented are dropped
    assert {"progress": "Writing the guide…"} in events
    assert state["guide_title"] == "Install the unit"
    assert len(state["sections"]) == 2


async def test_per_turn_state_resets_between_turns_on_one_thread():
    router = FakeModel({RouteDecision: [_decision("guide"), _decision("easy")]})
    model = _guide_model()
    model.texts.append("plain answer")
    retriever = FakeRetriever({"": [passage("some text")]})
    agent = _agent(router, model, retriever)

    await _run(agent, "guide me")
    _, state = await _run(agent, "what is x?")

    assert state["route"] == "easy"
    assert state["sections"] == [] and state["prerequisites"] == []
    assert len(state["excerpts"]) == 1


@pytest.mark.parametrize("route", ["easy", "hard", "guide"])
async def test_only_declared_event_kinds_reach_the_stream(route):
    router = FakeModel({RouteDecision: [_decision(route)]})
    model = _guide_model()
    model.structured[Decomposition] = [Decomposition(sub_queries=["q"])]
    model.structured[Analysis] = [Analysis(sufficient=True, notes="n")]
    model.texts = ["answer text"]

    events, _ = await _run(
        _agent(router, model, FakeRetriever({"": [passage("t")]})), "q"
    )

    assert all(set(e) <= {"route", "progress", "chunk"} for e in events)


async def test_every_answer_prompt_ends_with_the_question_as_a_user_message():
    """A prompt with no user turn makes the model answer generically instead of from the excerpts."""
    for route in ("easy", "hard", "guide"):
        router = FakeModel({RouteDecision: [_decision(route, "What is the pressure?")]})
        model = _guide_model()
        model.structured[Decomposition] = [Decomposition(sub_queries=["q"])]
        model.structured[Analysis] = [Analysis(sufficient=True, notes="n")]
        model.texts = ["answer"]

        await _run(
            _agent(router, model, FakeRetriever({"": [passage("t")]})),
            "pressure?",
            thread=route,
        )

        final = model.prompts_for("stream")[-1]
        assert final[-1].type == "human", route
        assert final[-1].content == "What is the pressure?", route


async def test_guide_never_presents_steps_no_retrieved_excerpt_supports():
    """Subagent output citing ids it never retrieved is invention: it is dropped, not written up."""
    router = FakeModel({RouteDecision: [_decision("guide", "Connect it to Wi-Fi")]})
    model = _guide_model()
    model.structured[SectionSteps] = [
        SectionSteps(
            steps=[
                Step(text="Open the app", excerpt_ids=[5]),
                Step(text="Pair it", excerpt_ids=[6]),
            ],
            warnings=[Step(text="Keep the app open", excerpt_ids=[7])],
        )
    ]
    model.structured[Prerequisites] = [
        Prerequisites(items=[Step(text="A phone", excerpt_ids=[9])])
    ]
    retriever = FakeRetriever({"": [passage("Nothing about wifi here.")]})

    await _run(_agent(router, model, retriever), "guide me to wifi")

    draft = model.prompts_for("stream")[0][0].content
    assert "Open the app" not in draft and "Pair it" not in draft
    assert "A phone" not in draft and "SECTION:" not in draft
    assert "the document contained no usable steps" in draft
