"""Single source of truth for every environment-derived name.

Nothing else in scripts/ builds a repository, state key or SSM name by hand.

ENV / AWS_REGION / AWS_PROFILE come from the Makefile (which exports them) and can
equally be set directly when running the CLI without make.
"""

from __future__ import annotations

import functools
import getpass
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .ui import die

# Config defaults shared with Terraform - terraform/config.tf reads the same file, so the
# model and Langfuse host `make compose-up` / `make run-agent` use are the ones a deploy
# uses. A single path, resolved from this file's location like shell.REPO_ROOT.
_DEFAULTS_PATH = Path(__file__).resolve().parents[2] / "terraform" / "defaults.json"


@functools.cache
def _shared_defaults() -> dict[str, object]:
    try:
        return json.loads(_DEFAULTS_PATH.read_text())
    except (OSError, ValueError) as error:
        raise die(
            f"cannot read shared config defaults at {_DEFAULTS_PATH}: {error}"
        ) from error


def required_env(name: str, purpose: str) -> str:
    """An environment variable a caller was supposed to set, with no safe default.

    Read through here rather than with os.environ[name] so a missing one fails with what
    it is for, instead of a KeyError traceback naming a bare string.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise die(f"{name} is not set - {purpose}")
    return value


def _default_profile() -> str:
    """Three cases, in priority order.

    set (even to empty)  honour it - an explicit empty value means "no profile"
    unset, under CI      no profile: a CI runner authenticates through GitHub OIDC, which
                         exports credentials as environment variables and writes no
                         ~/.aws/config - so `--profile default` fails outright, and so
                         does an AWS_PROFILE exported as an empty string, which is why
                         this is decided here rather than in each workflow's env block
    unset, on a laptop   the profile the AWS CLI would have used anyway
    """
    if "AWS_PROFILE" in os.environ:
        return os.environ["AWS_PROFILE"]
    if os.environ.get("CI"):
        return ""
    return "default"


def _dev_username() -> str:
    """The local username, reduced to what a container tag may contain.

    Falls back rather than raising: getpass reads the passwd database when no USER is
    exported, and a container without an entry for its uid raises there - which would
    fail every command, including the ones in CI that never look at an image tag.
    """
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]", "", user) or "unknown"


@dataclass(frozen=True)
class Config:
    env: str
    region: str
    profile: str
    image_tag: str

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ.get("ENV") or "dev"
        # Personal dev images are tagged dev-<username>-<UTC timestamp>: a tag that never changed would
        # leave Terraform with no diff, so the runtime and the ECS service would keep the old image.
        # CI publishes sha-<git-sha> instead.
        image_tag = os.environ.get("IMAGE_TAG") or (
            f"dev-{_dev_username()}-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
        )
        return cls(
            env=env,
            region=os.environ.get("AWS_REGION") or "eu-central-1",
            profile=_default_profile(),
            image_tag=image_tag,
        )

    @property
    def agent_ecr_repository(self) -> str:
        return f"doc-pipeline-agent-{self.env}"

    @property
    def api_ecr_repository(self) -> str:
        return f"doc-pipeline-api-{self.env}"

    @property
    def tf_state_key(self) -> str:
        """Every environment (preview environments included) keeps its own state object."""
        return f"{self.env}/terraform.tfstate"

    @property
    def tf_var_file(self) -> str | None:
        """The committed tfvars for a named environment; previews pass -var env=... instead."""
        return (
            f"envs/{self.env}.tfvars"
            if self.env in {"dev", "staging", "prod"}
            else None
        )

    @property
    def langfuse_ssm_parameter(self) -> str:
        return f"/doc-pipeline-agent/{self.env}/langfuse"

    @property
    def bedrock_model_id(self) -> str:
        """The model a locally-run agent talks to.

        BEDROCK_MODEL_ID in the environment wins (A/B a model without editing anything),
        else the shared default terraform/config.tf also reads for a dev deploy. prod pins
        its own value in that file - this is only ever the dev/local answer.
        """
        return str(
            os.environ.get("BEDROCK_MODEL_ID") or _shared_defaults()["bedrockModelId"]
        )

    @property
    def bedrock_temperature(self) -> float:
        """The sampling temperature a locally-run agent uses.

        BEDROCK_TEMPERATURE in the environment wins, else the shared default
        terraform/config.tf also reads for a deploy. Not per-environment.
        """
        override = os.environ.get("BEDROCK_TEMPERATURE", "").strip()
        return float(override or _shared_defaults()["bedrockTemperature"])

    @property
    def langfuse_base_url(self) -> str:
        """The Langfuse host. LANGFUSE_BASE_URL wins (self-hosted Langfuse), else the
        shared default; terraform/config.tf defaults the deployed side to the same value."""
        return str(
            os.environ.get("LANGFUSE_BASE_URL") or _shared_defaults()["langfuseBaseUrl"]
        )

    @property
    def prompt_label(self) -> str:
        """The Langfuse label this environment publishes and reads its prompts under.

        One label per environment, prod included: it used to be the literal "production"
        everywhere, which meant a dev or staging prompt sync republished the prompts
        production was serving the moment two environments shared a Langfuse project.
        Keeping prod's label symmetric with the rest is the point - a special case for
        prod is exactly how that bug came back.
        terraform/modules/agentcore passes the same value to the deployed
        agent as PROMPT_LABEL, which is what makes the writer and the reader agree.
        """
        return self.env

    @property
    def is_managed(self) -> bool:
        """True for the environments CI/CD owns exclusively; see Context.refuse_managed."""
        return self.env in {"prod", "staging"}
