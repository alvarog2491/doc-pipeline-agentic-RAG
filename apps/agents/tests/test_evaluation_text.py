import pytest
from evaluators.text import (
    ABSTENTION,
    fact_present,
    first_positions,
    is_consecutive_from_one,
    markers,
    normalise,
    numbered_items,
)


@pytest.mark.parametrize(
    "answer,fact",
    [
        ("Water must not exceed 40 °C.", "40 degrees Celsius"),
        ("The limit is 40°C", "40 °C"),
        ("Pressure: 6 BAR max", "6 bar"),
        ("It measures 30 x 15 x 40 cm", "30x15x40"),
        ("hold it for five seconds", ["5 seconds", "five seconds"]),
    ],
)
def test_facts_match_across_spelling_and_case(answer, fact):
    assert fact_present(answer, fact)


def test_absent_facts_and_empty_options_do_not_match():
    assert not fact_present("It weighs 3.2 kg", "6 bar")
    assert not fact_present("anything", ["", "   "])


def test_normalise_drops_punctuation_and_unit_words():
    assert normalise("40 degrees Celsius") == normalise("40°C") == "40c"


@pytest.mark.parametrize(
    "text",
    [
        "The handbook does not mention Wi-Fi.",
        "The document doesn't cover pricing.",
        "I could not find any information about that.",
        "That is not covered in the manual.",
        "There is no information on the X300.",
        "The document does not specifically describe it.",
    ],
)
def test_abstention_phrases_are_recognised(text):
    assert ABSTENTION.search(text)


def test_confident_answers_are_not_abstentions():
    assert not ABSTENTION.search("The maximum pressure is 6 bar [[1]].")


def test_markers_and_numbered_items_are_extracted_in_order():
    assert markers("a [[2]] b [[1]][[2]]") == [2, 1, 2]
    text = "# Guide\n1. First\n2. Second\n\n**3.** Third\n   4) Fourth"
    assert numbered_items(text) == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "numbers,ok",
    [
        ([1, 2, 3], True),
        ([1, 2, 1, 2, 3], True),
        ([1, 3], False),
        ([2, 3], False),
        ([], False),
        ([1, 1, 2], True),
    ],
)
def test_consecutive_numbering_allows_per_section_restarts(numbers, ok):
    assert is_consecutive_from_one(numbers) is ok


def test_first_positions_are_indexes_of_the_numbered_steps_that_carry_each_keyword():
    answer = "Intro mentions the bracket.\n1. Turn off the water supply.\n2. Mount the bracket.\n"

    positions = first_positions(
        answer, [["water supply"], ["bracket", "mount"], ["missing"]]
    )

    assert positions == [0, 1, None]  # the intro's "bracket" is not a step
