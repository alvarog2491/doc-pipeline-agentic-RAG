"""Test aggregate score thresholds used by the release gate."""

from utils.thresholds import check_regressions

THRESHOLDS = {"keyfact_recall": 0.80, "citation_validity": 0.95}


def test_passes_when_every_mean_clears_its_minimum():
    scores = {"keyfact_recall": [0.9, 0.85], "citation_validity": [1.0, 1.0]}
    assert check_regressions(scores, THRESHOLDS, item_count=2) == []


def test_fails_when_a_mean_falls_below_its_minimum():
    scores = {"keyfact_recall": [0.5], "citation_validity": [1.0]}
    assert check_regressions(scores, THRESHOLDS, item_count=1) == [
        ("keyfact_recall", 0.5, 0.80)
    ]


def test_judges_the_mean_rather_than_each_item():
    scores = {"keyfact_recall": [0.5, 1.0, 1.0], "citation_validity": [1.0, 1.0, 1.0]}
    assert check_regressions(scores, THRESHOLDS, item_count=3) == []


def test_a_run_with_no_items_fails():
    assert check_regressions({}, THRESHOLDS, item_count=0) != []


def test_a_score_nothing_produced_is_skipped_not_failed(caplog):
    scores = {"keyfact_recall": [0.9]}
    assert (
        check_regressions(
            scores, {**THRESHOLDS, "citation_validity": 0.9}, item_count=1
        )
        == []
    )
    assert "citation_validity" in caplog.text
