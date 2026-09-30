"""Publishing apps/agents/prompts/*.yaml to Langfuse under this environment's label."""

from __future__ import annotations

import json

from ..context import Context
from ..shell import require, uv_script
from ..ui import die

SYNC_PROMPTS_SCRIPT = "scripts/prompts/sync_prompts.py"


def sync(ctx: Context) -> None:
    """Push the committed prompt sources, so the deployed agent loads them by label.

    Credentials come from SSM, where they are bootstrapped once per environment (README
    "First-time bootstrap"); they are never created or rotated here.

    PROMPT_LABEL is passed explicitly rather than left to the environment: it is derived
    from ENV, and a stale value in .env would otherwise republish the prompts some other
    environment is serving.
    """
    require("uv")
    ctx.load_dotenv()

    credentials = json.loads(ctx.aws.ssm_parameter(ctx.config.langfuse_ssm_parameter))
    public_key = credentials.get("publicKey") or ""
    secret_key = credentials.get("secretKey") or ""
    if not public_key or not secret_key:
        raise die(
            f"{ctx.config.langfuse_ssm_parameter} is missing publicKey/secretKey - "
            "see README.md 'First-time bootstrap'"
        )

    uv_script(
        SYNC_PROMPTS_SCRIPT,
        env=ctx.child_env(
            LANGFUSE_PUBLIC_KEY=public_key,
            LANGFUSE_SECRET_KEY=secret_key,
            PROMPT_LABEL=ctx.config.prompt_label,
        ),
    )
