"""Running the Langfuse evaluation datasets against the deployed agent from a laptop.

`.github/workflows/cd-staging.yml` runs these on every pull request; this is the same
steps for a local run - publish the evaluation handbook, upsert the dataset(s), then run
the experiment script's `main()` against the agent behind `AGENT_GATEWAY_URL` (the deployed
environment's Gateway by default, or a `make compose-up` container when that variable
points at http://localhost:8080).

Every score is deterministic (no LLM judge), so a run costs only the agent invocations.
The scripts live in apps/agents and import its package, so they run through that
workspace's `uv` environment (`uv run --package DocPipelineAgent`), not this CLI's.
"""

from __future__ import annotations

import os

from .. import github, terraform
from ..context import Context
from ..shell import REPO_ROOT, require, run
from ..ui import Failure, Stages, info

AGENTS_DIR = REPO_ROOT / "apps" / "agents"

# The local `make compose-up` agents container serves the identical POST /invocations,
# text/event-stream contract on this port (docker-compose.yml maps 8080:8080).
_LOCAL_GATEWAY_URL = "http://localhost:8080"

# route -> (dataset upsert script, experiment script), relative to apps/agents. These
# mirror the matrix in cd-staging.yml - change one and the staging gate and the local run
# diverge.
ROUTES = {
    "easy": (
        "evaluations/datasets/create_easy_dataset.py",
        "evaluations/experiments/run_easy_experiment.py",
    ),
    "hard": (
        "evaluations/datasets/create_hard_dataset.py",
        "evaluations/experiments/run_hard_experiment.py",
    ),
    "guide": (
        "evaluations/datasets/create_guide_dataset.py",
        "evaluations/experiments/run_guide_experiment.py",
    ),
}


def _try_output(ctx: Context, name: str) -> str:
    try:
        return terraform.output(ctx, name)
    except Failure:
        return ""


def _experiment_env(ctx: Context) -> dict[str, str]:
    """What the dataset and experiment scripts read, beyond AWS credentials.

    LANGFUSE_SSM_PARAMETER_NAME points the scripts at this environment's bootstrapped
    credentials. The Gateway URL, documents bucket and registry table come from Terraform
    outputs; a caller-exported AGENT_GATEWAY_URL always wins, and with no deployed gateway
    the local agents container is targeted.
    """
    overrides = {
        "LANGFUSE_SSM_PARAMETER_NAME": ctx.config.langfuse_ssm_parameter,
        "LANGFUSE_BASE_URL": ctx.config.langfuse_base_url,
        "BEDROCK_MODEL_ID": ctx.config.bedrock_model_id,
        "BEDROCK_TEMPERATURE": str(ctx.config.bedrock_temperature),
    }
    if not os.environ.get("AGENT_GATEWAY_URL"):
        gateway = _try_output(ctx, "gateway_url")
        if gateway:
            overrides["AGENT_GATEWAY_URL"] = gateway
        else:
            info(
                f"no deployed gateway - targeting the local agents container at {_LOCAL_GATEWAY_URL}"
            )
            overrides["AGENT_GATEWAY_URL"] = _LOCAL_GATEWAY_URL
    for variable, output in (
        ("DOCUMENTS_BUCKET", "documents_bucket"),
        ("REGISTRY_TABLE", "registry_table"),
    ):
        if value := _try_output(ctx, output):
            overrides.setdefault(variable, value)
    return ctx.child_env(**overrides)


def _uv(script: str, env: dict[str, str]) -> None:
    run(
        ["uv", "run", "--package", "DocPipelineAgent", "python", script],
        env=env,
        cwd=AGENTS_DIR,
    )


_FIXTURE_SNIPPET = (
    "import sys; sys.path.insert(0, 'evaluations'); "
    "from fixture.document import ensure_fixture_document; print(ensure_fixture_document())"
)


def _publish_fixture(env: dict[str, str]) -> str:
    """Publish the evaluation handbook through the real pipeline; return its Knowledge Base id."""
    result = run(
        [
            "uv",
            "run",
            "--package",
            "DocPipelineAgent",
            "python",
            "-c",
            _FIXTURE_SNIPPET,
        ],
        env=env,
        cwd=AGENTS_DIR,
        capture=True,
    )
    return result.stdout.strip().splitlines()[-1]


def _prepare(ctx: Context) -> None:
    ctx.load_dotenv()
    ctx.refuse_managed()
    require("uv")


def prepare(ctx: Context) -> None:
    """Publish the evaluation handbook and print its Knowledge Base id as ``EVAL_KNOWLEDGE_BASE_ID=``.

    CI runs this once, then hands the id to every experiment so they skip ingestion.
    """
    require("uv")
    knowledge_base_id = _publish_fixture(_experiment_env(ctx))
    print(f"EVAL_KNOWLEDGE_BASE_ID={knowledge_base_id}")
    github.output("eval_knowledge_base_id", knowledge_base_id)


def sync_datasets(ctx: Context) -> None:
    """Make every Langfuse evaluation dataset match its version-controlled JSON.

    Listed items are upserted, items the file no longer lists are archived. No experiment run.
    """
    _prepare(ctx)
    env = _experiment_env(ctx)
    stages = Stages(len(ROUTES))
    for dataset_script, _ in ROUTES.values():
        stages.stage(f"sync dataset: {dataset_script}")
        _uv(dataset_script, env)
    stages.done()


def _run_routes(ctx: Context, routes: list[str]) -> None:
    _prepare(ctx)
    env = _experiment_env(ctx)
    stages = Stages(1 + 2 * len(routes))
    stages.stage("publish the evaluation handbook")
    if "EVAL_KNOWLEDGE_BASE_ID" not in env:
        env["EVAL_KNOWLEDGE_BASE_ID"] = _publish_fixture(env)
    for route in routes:
        dataset_script, experiment_script = ROUTES[route]
        stages.stage(f"sync dataset: {dataset_script}")
        _uv(dataset_script, env)
        stages.stage(f"run experiment: {experiment_script}")
        _uv(experiment_script, env)
    stages.done()


def run_route(ctx: Context, route: str) -> None:
    """Sync one route's dataset, then run its experiment (easy | hard | guide)."""
    _run_routes(ctx, [route])


def all_experiments(ctx: Context) -> None:
    """Every route's experiment, in the order cd-staging.yml runs them."""
    _run_routes(ctx, list(ROUTES))
