"""Exceptions and error-surfacing helpers shared across the evaluations package.

Every custom exception the evaluation tooling raises lives here so callers have one place
to import from and one hierarchy to catch. ``EvaluationError`` is the common base.
"""

import logging
import traceback

from langfuse import RegressionError

_LANGFUSE_LOGGER_NAME = "langfuse"


class EvaluationError(RuntimeError):
    """Base class for every error raised by the evaluation tooling."""


class ExperimentItemsFailedError(RegressionError, EvaluationError):
    """One or more dataset items never completed their task.

    Langfuse's experiment runner drops an item whose task raises, so a crashed item would
    otherwise silently lower the averaged scores instead of failing the run. This carries
    the ``(dataset_item_id, session_id)`` pairs so the offending sessions can be pulled
    from Langfuse. It subclasses ``RegressionError`` so the CI experiment-action still
    treats it as a gate failure.

    Attributes:
        failed_items: ``(dataset_item_id, session_id)`` for every item that never
            completed.
    """

    def __init__(self, *, result, failed_items, message: str) -> None:
        """Initialize the error.

        Args:
            result: The completed Langfuse experiment result.
            failed_items: Iterable of ``(dataset_item_id, session_id)`` pairs for the
                items whose task raised.
            message: Human-readable gate-failure message.
        """
        super().__init__(result=result, message=message)
        self.failed_items = list(failed_items)


class LangfuseItemErrorFilter(logging.Filter):
    """Fold the real exception into Langfuse's terse per-item failure log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record in place; always keeps the record.

        Args:
            record: The log record Langfuse is about to emit.

        Returns:
            Always ``True`` - the filter only mutates, it never drops records.
        """
        if not isinstance(record.args, tuple) or "failed:" not in str(record.msg):
            return True
        exc = record.args[-1]
        if isinstance(exc, BaseException):
            rendered = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).rstrip()
            record.args = record.args[:-1] + (f"{exc!r}\n{rendered}",)
        return True


def install_langfuse_item_error_logging() -> None:
    """Attach ``LangfuseItemErrorFilter`` to the Langfuse logger once (idempotent)."""
    langfuse_logger = logging.getLogger(_LANGFUSE_LOGGER_NAME)
    if any(isinstance(f, LangfuseItemErrorFilter) for f in langfuse_logger.filters):
        return
    langfuse_logger.addFilter(LangfuseItemErrorFilter())
