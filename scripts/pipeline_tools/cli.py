"""The command surface, and the one place a command's failure becomes an exit code.

Every command is `docpipe <group> <command>`; run `uv run scripts/docpipe.py --help` or
`... <group> --help` for the list. Arguments that are configuration rather than input
(ENV, AWS_REGION, AWS_PROFILE, FORCE, ...) arrive as environment variables - the Makefile
exports them and the workflows set them in an `env:` block.
"""

from __future__ import annotations

import argparse
import os

from .commands import agent, deploy, docs, experiments, local, prompts
from .shell import REPO_ROOT
from .ui import Failure, info


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docpipe",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    groups = parser.add_subparsers(dest="group", required=True)

    # --- deploy ---------------------------------------------------------------
    deploy_group = groups.add_parser(
        "deploy", help="deploy, verify and destroy an environment"
    )
    deploy_commands = deploy_group.add_subparsers(dest="command", required=True)
    deploy_commands.add_parser(
        "dev", help="everything: repositories, both images, all Terraform modules, ECS"
    ).set_defaults(handler=lambda ctx, args: deploy.deploy(ctx))
    destroy = deploy_commands.add_parser(
        "destroy", help="destroy every resource in this environment"
    )
    destroy.add_argument(
        "--yes", action="store_true", help="skip the typed confirmation"
    )
    destroy.set_defaults(
        handler=lambda ctx, args: deploy.destroy(ctx, assume_yes=args.yes)
    )
    deploy_commands.add_parser(
        "outputs",
        help="print the Terraform outputs as key=value (also to $GITHUB_OUTPUT)",
    ).set_defaults(handler=lambda ctx, args: deploy.outputs(ctx))
    deploy_commands.add_parser(
        "verify",
        help="ECS, the load balancer, CloudFront and the agent actually serve traffic",
    ).set_defaults(handler=lambda ctx, args: deploy.verify(ctx))

    # --- agent ----------------------------------------------------------------
    agent_group = groups.add_parser("agent", help="the deployed AgentCore runtime")
    agent_commands = agent_group.add_subparsers(dest="command", required=True)
    agent_commands.add_parser(
        "smoke-test", help="one signed call through the Gateway, asserting an answer"
    ).set_defaults(handler=lambda ctx, args: agent.smoke_test(ctx))

    # --- docs -----------------------------------------------------------------
    docs_group = groups.add_parser(
        "docs", help="the documents the ingestion pipeline turns into Knowledge Bases"
    )
    docs_commands = docs_group.add_subparsers(dest="command", required=True)
    upload = docs_commands.add_parser(
        "upload",
        help="upload a PDF; Textract, chunking and a new Knowledge Base follow",
    )
    upload.add_argument("pdf", metavar="PDF")
    upload.add_argument(
        "--wait", action="store_true", help="block until the document is READY"
    )
    upload.set_defaults(
        handler=lambda ctx, args: docs.upload(ctx, args.pdf, wait=args.wait)
    )
    docs_commands.add_parser(
        "list", help="every ingested document with its status and Knowledge Base id"
    ).set_defaults(handler=lambda ctx, args: docs.list_documents(ctx))

    # --- prompts --------------------------------------------------------------
    prompt_group = groups.add_parser("prompts", help="the Langfuse prompt sources")
    prompt_commands = prompt_group.add_subparsers(dest="command", required=True)
    prompt_commands.add_parser(
        "sync", help="push apps/agents/prompts/*.yaml under this environment's label"
    ).set_defaults(handler=lambda ctx, args: prompts.sync(ctx))

    # --- experiments ----------------------------------------------------------
    experiment_group = groups.add_parser(
        "experiments",
        help="run the deterministic Langfuse evaluations against the deployed agent",
    )
    experiment_commands = experiment_group.add_subparsers(dest="command", required=True)
    experiment_commands.add_parser(
        "prepare", help="publish the evaluation handbook; print EVAL_KNOWLEDGE_BASE_ID="
    ).set_defaults(handler=lambda ctx, args: experiments.prepare(ctx))
    experiment_commands.add_parser(
        "sync-datasets",
        help="make every Langfuse dataset match its raw_datasets/*.json",
    ).set_defaults(handler=lambda ctx, args: experiments.sync_datasets(ctx))
    for route in experiments.ROUTES:
        experiment_commands.add_parser(
            route, help=f"upsert the {route} dataset, then run its experiment"
        ).set_defaults(
            handler=lambda ctx, args, route=route: experiments.run_route(ctx, route)
        )
    experiment_commands.add_parser(
        "all", help="every experiment, in the order cd-staging.yml runs them"
    ).set_defaults(handler=lambda ctx, args: experiments.all_experiments(ctx))

    # --- local ----------------------------------------------------------------
    local_group = groups.add_parser("local", help="local development against dev")
    local_commands = local_group.add_subparsers(dest="command", required=True)
    local_commands.add_parser(
        "compose-up",
        help="build and run the local containers; creds + outputs resolved at launch",
    ).set_defaults(handler=lambda ctx, args: local.compose_up(ctx))
    local_commands.add_parser(
        "run-agent",
        help="run apps/agents from source (no Docker) against the deployed dev environment",
    ).set_defaults(handler=lambda ctx, args: local.run_agent(ctx))
    local_commands.add_parser(
        "frontend-dev", help="run the local frontend against the deployed dev API"
    ).set_defaults(handler=lambda ctx, args: local.frontend_dev(ctx))

    return parser


def main(argv: list[str] | None = None) -> None:
    # Every relative path in this CLI - a Dockerfile, terraform/, .env - means the same
    # thing from anywhere.
    os.chdir(REPO_ROOT)

    from .context import Context

    args = _build_parser().parse_args(argv)
    try:
        args.handler(Context(), args)
    except Failure as failure:
        info(f"\nERROR: {failure}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        info("\ninterrupted")
        raise SystemExit(130) from None
