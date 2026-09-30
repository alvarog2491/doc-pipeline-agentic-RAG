"""Text helpers for deterministic scoring: normalisation, fact matching and step order."""

from __future__ import annotations

import re
from collections.abc import Sequence

_MARKER = re.compile(r"\[\[(\d+)\]\]")
_NUMBERED_ITEM = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(\d+)[.)](?:\*\*)?\s+\S", re.MULTILINE
)

# Phrases an answer uses to say the document does not contain the requested information.
ABSTENTION = re.compile(
    r"(does not|doesn't|do not|don't|did not|didn't|cannot|can't|is not|isn't|are not|aren't)"
    r"\s+(?:\w+\s+){0,4}?(cover|mention|contain|state|specify|describe|include|provide|say|list|address|discuss|have)"
    r"|(?:could not|couldn't|unable to|cannot|can't)\s+find"
    r"|no (?:information|mention|details?|data)"
    r"|not (?:covered|mentioned|stated|specified|described|included|available|provided)",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    """Casefold and drop everything but letters and digits, so ``40 °C`` equals ``40°c``."""
    return re.sub(
        r"[^0-9a-z]+",
        "",
        text.casefold().replace("degrees celsius", "c").replace("degrees", "c"),
    )


def fact_present(answer: str, alternatives: str | Sequence[str]) -> bool:
    """Return whether the answer states a fact, in any of its accepted spellings.

    Args:
        answer: Answer text.
        alternatives: One accepted phrase, or several alternative phrasings.
    """
    options = [alternatives] if isinstance(alternatives, str) else list(alternatives)
    haystack = normalise(answer)
    return any(normalise(option) in haystack for option in options if normalise(option))


def markers(answer: str) -> list[int]:
    """Return every ``[[n]]`` citation marker in the raw answer, in order."""
    return [int(n) for n in _MARKER.findall(answer)]


def numbered_items(answer: str) -> list[int]:
    """Return the numbers of the numbered list items in Markdown text, in order."""
    return [int(n) for n in _NUMBERED_ITEM.findall(answer)]


def is_consecutive_from_one(numbers: list[int]) -> bool:
    """Return whether a list of item numbers runs 1, 2, 3... without gaps or repeats.

    A guide split into sections may restart numbering per section, so a restart to 1 is
    accepted as long as every run is itself consecutive.
    """
    if not numbers:
        return False
    expected = 1
    for number in numbers:
        if number == 1:
            expected = 1
        if number != expected:
            return False
        expected += 1
    return True


def numbered_item_texts(answer: str) -> list[str]:
    """Return the text of each numbered list item (a step), continuation lines included."""
    items: list[str] = []
    for line in answer.splitlines():
        if _NUMBERED_ITEM.match(line):
            items.append(line)
        elif items and line.strip() and not line.lstrip().startswith(("#", "-")):
            items[-1] += " " + line.strip()
    return items


def first_positions(
    answer: str, steps: Sequence[str | Sequence[str]]
) -> list[int | None]:
    """Locate each required step by the first numbered step that mentions one of its keywords.

    Only numbered steps are searched, so a keyword in a title, a prerequisite list or a warning
    ("Before you start...") cannot pass for the step itself.

    Args:
        answer: The guide text.
        steps: For each required step, a keyword or alternative keywords.

    Returns:
        The index of the numbered step that carries each required step, or ``None`` when absent.
    """
    items = [item.casefold() for item in numbered_item_texts(answer)]
    positions: list[int | None] = []
    for step in steps:
        options = [step] if isinstance(step, str) else list(step)
        found = [
            i
            for i, item in enumerate(items)
            if any(option.casefold() in item for option in options)
        ]
        positions.append(found[0] if found else None)
    return positions
