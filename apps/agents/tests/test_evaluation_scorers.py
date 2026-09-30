from evaluators.scorers import INFORMATIONAL, TTFT_BUDGET_MS, score_run


def _scores(output, **expect):
    return {e.name: e for e in score_run(output={**output, "expectations": expect})}


def _run(**overrides):
    base = {
        "answer": "The maximum operating pressure is 6 bar [[1]].",
        "route": "easy",
        "citations": [{"id": 1, "page": 1, "source": "uploads/a.pdf", "section": ""}],
        "diagnostics": {
            "retrievals": 1,
            "retrieved": [{"id": 1, "page": 1, "source": "uploads/a.pdf"}],
            "sections": 0,
            "prerequisites": 0,
        },
        "ttft_ms": 900.0,
        "latency_ms": 2500.0,
    }
    return {**base, **overrides}


def test_a_correct_easy_answer_scores_perfectly_on_every_applicable_metric():
    scores = _scores(
        _run(),
        expected_route="easy",
        expected_pages=[1],
        key_facts=["6 bar"],
        forbidden=["10 bar"],
        answerable=True,
    )

    for name, evaluation in scores.items():
        if name not in INFORMATIONAL:
            assert evaluation.value == 1.0, (name, evaluation.comment)
    assert scores["retrieval_mrr"].value == 1.0


def test_wrong_route_is_penalised_with_a_helpful_comment():
    scores = _scores(_run(route="hard"), expected_route="easy")

    assert scores["route_accuracy"].value == 0.0
    assert "expected easy, got hard" in scores["route_accuracy"].comment


def test_retrieval_recall_is_the_share_of_expected_pages_retrieved():
    output = _run(
        diagnostics={
            "retrievals": 2,
            "retrieved": [
                {"id": 1, "page": 4, "source": "s"},
                {"id": 2, "page": 1, "source": "s"},
            ],
        }
    )

    scores = _scores(output, expected_pages=[1, 2])

    assert scores["retrieval_recall"].value == 0.5
    assert scores["retrieval_mrr"].value == 0.5  # first expected page is at rank 2


def test_citations_must_exist_resolve_and_point_at_expected_pages():
    output = _run(
        answer="Fact [[1]] and invented [[9]].",
        citations=[{"id": 1, "page": 3, "source": "s", "section": ""}],
    )

    scores = _scores(output, expected_pages=[1])

    assert scores["citation_presence"].value == 1.0
    assert scores["citation_validity"].value == 0.5  # [[9]] resolves to nothing
    assert scores["citation_accuracy"].value == 0.0  # the resolved page is wrong


def test_an_answer_without_citations_fails_presence_and_validity():
    scores = _scores(_run(answer="6 bar.", citations=[]), expected_pages=[1])

    assert scores["citation_presence"].value == 0.0
    assert scores["citation_validity"].value == 0.0


def test_missing_facts_are_named_and_forbidden_claims_fail():
    scores = _scores(
        _run(answer="Pressure is 10 bar."),
        key_facts=["6 bar", "3.2 kg"],
        forbidden=["10 bar"],
    )

    assert scores["keyfact_recall"].value == 0.0
    assert "6 bar" in scores["keyfact_recall"].comment
    assert scores["no_forbidden_claims"].value == 0.0


def test_unanswerable_questions_reward_abstention_and_punish_invented_citations():
    good = _scores(
        _run(answer="The handbook does not cover pricing.", citations=[]),
        answerable=False,
    )
    bad = _scores(_run(answer="It costs 99 [[1]].", citations=[]), answerable=False)

    assert good["abstention_correct"].value == 1.0
    assert good["citation_validity"].value == 1.0
    assert bad["abstention_correct"].value == 0.0
    assert bad["citation_validity"].value == 0.0


def test_refusing_an_answerable_question_is_penalised():
    scores = _scores(
        _run(answer="The document does not mention the pressure."),
        answerable=True,
        key_facts=["6 bar"],
    )

    assert scores["abstention_correct"].value == 0.0


GUIDE = "# Install\n1. Turn off the water supply\n2. Mount the bracket\n3. Connect the inlet hose\n"


def test_guide_coverage_order_and_numbering():
    steps = [["water supply"], ["bracket"], ["inlet hose"]]

    good = _scores(_run(answer=GUIDE, route="guide"), required_steps=steps)
    reordered = _scores(
        _run(
            answer="1. Connect the inlet hose\n2. Mount the bracket\n3. Turn off the water supply",
            route="guide",
        ),
        required_steps=steps,
    )
    gappy = _scores(
        _run(
            answer="1. Turn off the water supply\n3. Mount the bracket\n4. inlet hose",
            route="guide",
        ),
        required_steps=steps,
    )

    assert good["guide_step_coverage"].value == 1.0
    assert good["guide_order_validity"].value == 1.0
    assert good["guide_numbering"].value == 1.0
    assert reordered["guide_step_coverage"].value == 1.0
    assert reordered["guide_order_validity"].value == 0.0
    assert gappy["guide_numbering"].value == 0.0


def test_guide_route_requires_subagent_sections_and_others_forbid_them():
    diagnostics = {"retrievals": 4, "retrieved": [], "sections": 3, "prerequisites": 1}

    guide = _scores(
        _run(route="guide", diagnostics=diagnostics),
        expected_route="guide",
        min_sections=2,
    )
    starved = _scores(
        _run(route="guide", diagnostics={**diagnostics, "sections": 1}),
        expected_route="guide",
        min_sections=2,
    )
    easy_delegating = _scores(
        _run(route="easy", diagnostics=diagnostics), expected_route="easy"
    )

    assert guide["subagent_use"].value == 1.0
    assert starved["subagent_use"].value == 0.0
    assert easy_delegating["subagent_use"].value == 0.0


def test_retrieval_budget_is_enforced_per_route():
    over = _scores(_run(diagnostics={"retrievals": 3, "retrieved": []}))
    none = _scores(_run(diagnostics={"retrievals": 0, "retrieved": []}))
    hard = _scores(_run(route="hard", diagnostics={"retrievals": 6, "retrieved": []}))

    assert over["tool_budget"].value == 0.0  # easy allows one
    assert none["tool_budget"].value == 0.0  # an answer with no retrieval is ungrounded
    assert hard["tool_budget"].value == 1.0


def test_time_to_first_token_is_checked_against_the_route_budget():
    fast = _scores(_run(ttft_ms=TTFT_BUDGET_MS["easy"] - 1))
    slow = _scores(_run(ttft_ms=TTFT_BUDGET_MS["easy"] + 1))
    silent = _scores(_run(ttft_ms=None, answer=""))

    assert fast["ttft_within_budget"].value == 1.0
    assert slow["ttft_within_budget"].value == 0.0
    assert silent["ttft_within_budget"].value == 0.0
    assert silent["answer_well_formed"].value == 0.0
    assert fast["latency_ms"].value == 2500.0


def test_scorers_only_emit_metrics_the_item_declares_expectations_for():
    assert set(_scores(_run())) == {
        "citation_presence",
        "citation_validity",
        "subagent_use",
        "tool_budget",
        "latency_ms",
        "ttft_ms",
        "ttft_within_budget",
        "answer_well_formed",
    }


def test_a_task_that_returned_nothing_scores_zero_instead_of_crashing():
    [evaluation] = score_run(output=None)

    assert evaluation.name == "answer_well_formed" and evaluation.value == 0.0


def test_a_keyword_in_an_intro_or_title_does_not_count_as_the_step():
    answer = (
        "# Install\nBefore you start you need a wrench.\n\n## Prerequisites\n- A cartridge\n\n"
        "1. Turn off the water supply\n2. Press the Start button\n"
    )
    steps = [["water supply"], ["start"]]

    scores = _scores(_run(answer=answer, route="guide"), required_steps=steps)

    assert scores["guide_step_coverage"].value == 1.0
    assert (
        scores["guide_order_validity"].value == 1.0
    )  # "start" is found in step 2, not in the intro


def test_a_step_missing_from_the_numbered_list_is_not_covered():
    scores = _scores(
        _run(
            answer="Prerequisites: a wrench\n1. Turn off the water supply",
            route="guide",
        ),
        required_steps=[["water supply"], ["wrench"]],
    )

    assert scores["guide_step_coverage"].value == 0.5


def test_an_abstention_may_cite_real_excerpts_but_never_invented_ones():
    real = _scores(
        _run(
            answer="The document does not cover pricing [[1]].",
            citations=[{"id": 1, "page": 1, "source": "s", "section": ""}],
        ),
        answerable=False,
    )
    invented = _scores(
        _run(answer="It costs 99 [[7]].", citations=[]), answerable=False
    )

    assert real["citation_validity"].value == 1.0
    assert invented["citation_validity"].value == 0.0
