"""Terminal output, and the one exception type a command may raise to fail cleanly.

Everything here writes to stderr. That is not a stylistic choice: several commands
return a value on stdout for their caller to capture - `deploy outputs` is
appended straight to $GITHUB_OUTPUT - so a progress line on stdout would corrupt it.
"""

from __future__ import annotations

import sys
import time


class Failure(Exception):
    """A command failing for a reason the user should read, not a stack trace.

    The CLI catches it, prints `ERROR: <message>` and exits 1 - the shell `die` this
    replaces, with the same contract.
    """


def die(message: str) -> Failure:
    """Build the exception. Written as `raise die(...)` so the caller reads as a stop."""
    return Failure(message)


def info(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def format_duration(total_seconds: float) -> str:
    """ "43s", "2m 03s", "1h 02m 03s"."""
    total = int(total_seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


class Stages:
    """Numbered banners for a multi-step command, and the elapsed total at the end.

    Declared with the total up front (`Stages(6)`) so a banner reads "[3/6]" rather than
    just "step 3" - the point being that a long deploy tells you how much is left. The
    clock starts at construction and measures this command only: a command that shells
    out to another one still reports its own total, not the child's.
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.index = 0
        self.started = time.monotonic()

    def stage(self, title: str) -> None:
        self.index += 1
        info(
            f"\n==================== [{self.index}/{self.total}] {title} ===================="
        )

    def done(self) -> None:
        elapsed = format_duration(time.monotonic() - self.started)
        info(f"\n========================= DONE in {elapsed} =========================")
