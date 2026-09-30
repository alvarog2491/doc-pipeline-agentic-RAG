"""What every command is handed: the resolved configuration and an AWS session.

One object rather than module-level globals because .env can change the answer. Loading
it re-derives everything downstream (see `load_dotenv`), and a global that had already
been computed would not move.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import env_file
from .aws import Aws, apply_environment
from .config import Config
from .shell import REPO_ROOT
from .ui import die


class Context:
    def __init__(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.config = Config.from_env()
        apply_environment(self.config)
        self.aws = Aws(self.config)

    @property
    def dotenv_path(self) -> Path:
        return REPO_ROOT / ".env"

    def load_dotenv(self) -> None:
        """Load .env into the environment, then re-derive everything named from it.

        The re-derivation is the whole point. .env is user-supplied, so without it a
        stale key there silently wins over a derived one: a .env carrying
        PROMPT_LABEL=dev made `ENV=prod docpipe prompts sync` publish prompts under the
        dev label. Rebuilding the config keeps that the right way round - the knobs it
        reads (ENV, AWS_REGION, AWS_PROFILE) still honour whatever .env set, while every
        name derived *from* those knobs is recomputed from the final values.
        """
        os.environ.update(env_file.parse(self.dotenv_path))
        self._refresh()

    def set_dotenv(self, key: str, value: str) -> None:
        env_file.upsert(self.dotenv_path, key, value)

    def refuse_managed(self) -> None:
        """Both prod and staging are deployed exclusively by CI/CD.

        Staging is the gate a change has to pass before it is allowed near prod, so a
        hand-run deploy into it does not just risk staging, it invalidates the evidence
        the next release is approved on. Named for what it does rather than for prod
        alone, since it guards two environments.
        """
        if self.config.is_managed:
            raise die(
                f"refusing to run against ENV={self.config.env} - it is deployed by "
                "CI/CD only (see .github/workflows/)."
            )

    def child_env(self, **overrides: str | None) -> dict[str, str]:
        """The environment for a subprocess: this one, plus explicit overrides.

        Overrides are how a derived value beats a stale .env entry of the same name in a
        child process - os.environ still carries what .env said, and passing the derived
        value explicitly is what makes the child agree with this process.
        """
        env = dict(os.environ)
        env.pop("VIRTUAL_ENV", None)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env
