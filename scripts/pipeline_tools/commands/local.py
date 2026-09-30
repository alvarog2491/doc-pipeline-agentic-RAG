"""Local development against the deployed dev environment."""

from __future__ import annotations

import os

from .. import terraform
from ..context import Context
from ..shell import REPO_ROOT, require, run
from ..ui import die


def _agent_env(ctx: Context, *, tracing_environment: str) -> dict[str, str]:
    """Everything the agent needs beyond AWS credentials, for a local run.

    The local counterpart of the env vars Terraform sets on the deployed Runtime
    (terraform/modules/agentcore): derived names from Config, and the model id, temperature
    and Langfuse host from terraform/defaults.json. Knowledge Bases are chosen per request
    (`knowledgeBaseId` in the payload), so no Knowledge Base wiring is needed here.

    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are left out on purpose - with
    LANGFUSE_SSM_PARAMETER_NAME set, the agent reads them from SSM itself.
    """
    return {
        "AWS_REGION": ctx.config.region,
        "BEDROCK_MODEL_ID": ctx.config.bedrock_model_id,
        "BEDROCK_TEMPERATURE": str(ctx.config.bedrock_temperature),
        "PROMPT_LABEL": ctx.config.prompt_label,
        "LANGFUSE_SSM_PARAMETER_NAME": ctx.config.langfuse_ssm_parameter,
        "LANGFUSE_BASE_URL": ctx.config.langfuse_base_url,
        "LANGFUSE_TRACING_ENVIRONMENT": tracing_environment,
    }


def _api_env(ctx: Context) -> dict[str, str]:
    """The API's registry and bucket, from the deployed dev environment."""
    return {
        "REGISTRY_TABLE": terraform.output(ctx, "registry_table"),
        "DOCUMENTS_BUCKET": terraform.output(ctx, "documents_bucket"),
    }


def _deployed_gateway_url(ctx: Context) -> str | None:
    """The deployed Gateway control-target URL when GATEWAY=deployed, else None.

    Default (None) leaves docker compose on its http://agents:8080 fallback - the local
    agents container, which serves the identical POST /invocations, text/event-stream
    contract. GATEWAY=deployed exercises the real Gateway/Runtime routing instead.
    """
    choice = os.environ.get("GATEWAY", "local").strip().lower()
    if choice in {"", "local"}:
        return None
    if choice == "deployed":
        return terraform.output(ctx, "gateway_url")
    raise die(f"GATEWAY must be 'local' or 'deployed', not {choice!r}")


def compose_up(ctx: Context) -> None:
    """Build and run the full local container set, with everything resolved at launch.

    Nothing is required in .env: everything is resolved here, on the host, and passed
    straight through to the containers. AWS credentials are resolved once by boto3 from the
    *active* profile (SSO, assume-role, MFA and credential_process all work), so the
    containers get only one short-lived, single-account credential set instead of a
    bind-mounted ~/.aws with every profile in it.
    """
    require("docker", "terraform")
    ctx.load_dotenv()
    ctx.refuse_managed()

    credentials = ctx.aws.session.get_credentials()
    if credentials is None:
        raise die(
            f"no AWS credentials for profile '{ctx.config.profile or '(environment)'}' - "
            "run `aws sso login` (or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) first"
        )
    ctx.aws.account_id()  # proves the credentials are valid *now*, with a clean message
    frozen = credentials.get_frozen_credentials()

    overrides = {
        "AWS_ACCESS_KEY_ID": frozen.access_key,
        "AWS_SECRET_ACCESS_KEY": frozen.secret_key,
        "AWS_SESSION_TOKEN": frozen.token,  # None for a static-key profile; child_env drops it
        "AWS_PROFILE": None,  # already resolved into the keys above
        **_agent_env(ctx, tracing_environment=f"{ctx.config.env}-docker"),
        **_api_env(ctx),
    }
    gateway_url = _deployed_gateway_url(ctx)
    if gateway_url is not None:
        overrides["AGENT_GATEWAY_URL"] = gateway_url

    run(
        ["docker", "compose", "up", "--build", "--watch"],
        env=ctx.child_env(**overrides),
        cwd=REPO_ROOT,
    )


def run_agent(ctx: Context) -> None:
    """Run apps/agents straight from source (no Docker) against the deployed dev environment.

    `uv run python main.py` from apps/agents, on http://localhost:8080. Credentials are the
    ambient ones (no container, so ~/.aws is fine here).
    """
    require("uv")
    ctx.load_dotenv()
    ctx.refuse_managed()

    run(
        ["uv", "run", "--package", "DocPipelineAgent", "python", "main.py"],
        env=ctx.child_env(
            **_agent_env(ctx, tracing_environment=f"{ctx.config.env}-local")
        ),
        cwd=REPO_ROOT / "apps" / "agents",
    )


def frontend_dev(ctx: Context) -> None:
    """Run the local Vite dev server against the deployed dev API.

    Writes apps/frontend/.env.local with the live load balancer as the proxy target, then
    starts the frontend on http://localhost:5173 proxying /v1 to it.
    """
    require("pnpm", "terraform")
    ctx.refuse_managed()

    target = f"http://{terraform.output(ctx, 'alb_dns_name')}"
    (REPO_ROOT / "apps" / "frontend" / ".env.local").write_text(
        f"API_PROXY_TARGET={target}\n"
    )
    run(
        ["pnpm", "--filter", "@doc-pipeline/frontend", "dev"],
        env=ctx.child_env(),
        cwd=REPO_ROOT,
    )
