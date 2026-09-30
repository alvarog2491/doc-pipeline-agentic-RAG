"""Writing to the GitHub Actions step files, when running under Actions.

Both are no-ops elsewhere, so a command behaves the same run by hand as run by a
workflow - the workflow just also gets a job output or a summary table out of it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _append(variable: str, text: str) -> None:
    path = os.environ.get(variable)
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(text)


def output(key: str, value: str) -> None:
    """A step output: `steps.<id>.outputs.<key>`."""
    _append("GITHUB_OUTPUT", f"{key}={value}\n")


def summary(report: str) -> None:
    """A block of Markdown on the job summary page, echoed to stderr either way."""
    print(report, file=sys.stderr)
    _append("GITHUB_STEP_SUMMARY", report + "\n\n")
