"""Repository layout, tool checks, and the one way this CLI starts a subprocess.

Subprocesses are still how the external tools run - `terraform`, `docker`, `pnpm`, and the
single-file Python scripts with their own dependency sets. `run` is a list-argv wrapper
around subprocess with no shell involved, so a value carrying a space, a quote or a `$`
is an argument rather than a parse.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .ui import die, info

# scripts/pipeline_tools/shell.py -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]


def require(*commands: str) -> None:
    """Fail with every missing tool listed at once, rather than one per re-run."""
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        raise die(f"missing required command(s): {' '.join(missing)}")


def run(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
    capture: bool = False,
    check: bool = True,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command. Raises Failure on a non-zero exit unless check=False.

    Output is inherited by default so a long `terraform apply` or `docker build` streams as it
    happens; capture=True is for the few places that need the text back. The argv is
    always echoed first - every caller here builds it from known flags and config, never
    from secrets, so it is safe to print verbatim.
    """
    where = f" (in {cwd})" if cwd is not None else ""
    info(f"$ {' '.join(argv)}{where}")
    # A list argv, never a shell string, so nothing in a value is ever parsed.
    result = subprocess.run(
        list(argv),
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd is not None else None,
        input=stdin,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        if capture and result.stderr:
            info(result.stderr.rstrip())
        raise die(f"`{' '.join(argv)}` failed with exit code {result.returncode}")
    return result


def uv_script(
    script: str,
    *,
    env: Mapping[str, str],
    extra_uv_args: Sequence[str] = (),
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one of the single-file scripts under scripts/ in its own ephemeral environment.

    Each of those scripts declares its dependencies inline (PEP 723), so there is no
    `--with` flag here and no `--no-project` either: `uv run` on a script carrying inline
    metadata ignores the uv workspace at the repository root by definition. That
    isolation is the reason they are not simply modules of this package - langfuse and
    boto3 have no business being installed to run a deploy.
    """
    return run(
        ["uv", "run", *extra_uv_args, script],
        env=env,
        cwd=REPO_ROOT,
        capture=capture,
        check=check,
    )


def confirm(prompt: str) -> bool:
    """A typed y/Y, read from the terminal. Anything else - EOF included - is no."""
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip() in {"y", "Y"}


def is_tty() -> bool:
    return sys.stdin.isatty()
