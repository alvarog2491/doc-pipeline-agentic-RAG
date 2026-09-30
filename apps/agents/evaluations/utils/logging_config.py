"""Configure colored console logging for evaluation scripts."""

import logging
import sys

_TIMESTAMP_COLOR = "\033[90m"  # gray
_LEVEL_COLOR = "\033[34m"  # blue
_MESSAGE_COLOR = "\033[37m"  # white
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    """Render the timestamp, level, and message in different colors."""

    def __init__(self) -> None:
        super().__init__(datefmt="%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        message = record.getMessage()
        return (
            f"{_TIMESTAMP_COLOR}{timestamp}{_RESET} "
            f"{_LEVEL_COLOR}{record.levelname}{_RESET} "
            f"{record.name}: {_MESSAGE_COLOR}{message}{_RESET}"
        )


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a timestamped, colorized console format.

    Falls back to a plain (uncolored) timestamped format when stderr is not a
    terminal, e.g. when output is piped to a file or captured by CI.

    Args:
        level: Minimum log level the root logger emits.
    """
    handler = logging.StreamHandler()
    if sys.stderr.isatty():
        handler.setFormatter(_ColorFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    logging.basicConfig(level=level, handlers=[handler])
