"""Reading and rewriting the repository's optional .env.

.env is a developer convenience for the local paths (docker compose, running apps/agents
directly). CI never has one.
"""

from __future__ import annotations

import re
from pathlib import Path

from .ui import info

# KEY=VALUE, tolerating a leading `export` and surrounding quotes, which is the subset
# `set -a; source ./.env` accepted and the subset upsert() writes.
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse(path: Path) -> dict[str, str]:
    """Every assignment in the file, in order, last one winning. Missing file: empty."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    return values


def _assigns(line: str, key: str) -> bool:
    """Whether `line` is an assignment to `key`, in any form `parse()` accepts."""
    match = _ASSIGNMENT.match(line)
    return match is not None and match.group(1) == key


def upsert(path: Path, key: str, value: str) -> None:
    """Replace any existing KEY= line (export-prefixed or not), or append one.

    Matched with the same rule `parse()` uses to read the key back, rather than a plain
    `startswith(f"{key}=")`: a `.env` written by hand with `export KEY=...` is valid
    input to `parse()`, and upsert has to recognise the same line as "existing" or it
    leaves the old value in place and appends a second, conflicting one instead of
    replacing it.

    Values are single-quoted so JSON and URLs survive being read back by anything that
    still sources this file - docker compose and the shell alike.
    """
    lines = path.read_text().splitlines() if path.is_file() else []
    kept = [line for line in lines if not _assigns(line, key)]
    kept.append(f"{key}='{value}'")
    path.write_text("\n".join(kept) + "\n")
    info(f"  .env: {key}='{value}'")
