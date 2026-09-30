"""Terraform invocations.

Terraform only ever provisions infrastructure here: it never builds or pushes an image -
that is this CLI's job. Every call runs against ``terraform/`` with the environment's own
remote state, selected through a partial backend configuration so the state bucket (whose
name contains the AWS account id) never has to live in a file.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence

from .context import Context
from .shell import REPO_ROOT, run
from .ui import die

TF_DIR = REPO_ROOT / "terraform"


def state_bucket(ctx: Context) -> str:
    """The bucket holding every environment's state: TF_STATE_BUCKET, else the bootstrap default."""
    return (
        os.environ.get("TF_STATE_BUCKET")
        or f"doc-pipeline-tfstate-{ctx.aws.account_id()}"
    )


def backend_args(ctx: Context) -> list[str]:
    """``-backend-config`` flags selecting this environment's state object."""
    return [
        f"-backend-config=bucket={state_bucket(ctx)}",
        f"-backend-config=key={ctx.config.tf_state_key}",
        f"-backend-config=region={ctx.config.region}",
        "-backend-config=use_lockfile=true",
    ]


def var_args(ctx: Context, variables: Mapping[str, str] | None) -> list[str]:
    """``-var-file`` / ``-var`` flags: the environment, the region, then explicit values.

    A None or empty value is omitted rather than passed empty, so the module's own default
    applies instead of a blank overriding it.
    """
    args = (
        [f"-var-file={ctx.config.tf_var_file}"]
        if ctx.config.tf_var_file
        else ["-var", f"env={ctx.config.env}"]
    )
    args += ["-var", f"region={ctx.config.region}"]
    for key, value in (variables or {}).items():
        if value:
            args += ["-var", f"{key}={value}"]
    return args


def _terraform(ctx: Context, *args: str, capture: bool = False):
    return run(
        ["terraform", f"-chdir={TF_DIR}", *args],
        env=ctx.child_env(TF_IN_AUTOMATION="1"),
        capture=capture,
    )


def init(ctx: Context) -> None:
    """``terraform init -reconfigure`` against this environment's state."""
    _terraform(ctx, "init", "-reconfigure", "-input=false", *backend_args(ctx))


def apply(
    ctx: Context,
    variables: Mapping[str, str] | None = None,
    *,
    targets: Sequence[str] = (),
) -> None:
    """``terraform apply`` (non-interactive), optionally limited to some targets.

    Args:
        ctx: Command context.
        variables: Extra ``-var`` values, such as the image tags to deploy.
        targets: Resource or module addresses for ``-target``.
    """
    init(ctx)
    target_args = [f"-target={target}" for target in targets]
    _terraform(
        ctx,
        "apply",
        "-auto-approve",
        "-input=false",
        *target_args,
        *var_args(ctx, variables),
    )


def destroy(ctx: Context) -> None:
    """``terraform destroy`` for this environment."""
    init(ctx)
    _terraform(ctx, "destroy", "-auto-approve", "-input=false", *var_args(ctx, None))


def outputs(ctx: Context) -> dict[str, object]:
    """Every Terraform output as ``{name: value}``.

    Raises:
        Failure: If the environment has not been applied yet.
    """
    init(ctx)
    result = _terraform(ctx, "output", "-json", capture=True)
    try:
        raw = json.loads(result.stdout or "{}")
    except ValueError as error:
        raise die(f"terraform output was not JSON: {error}") from error
    if not raw:
        raise die(
            f"no Terraform outputs for ENV={ctx.config.env} - run `make dev-deploy` first"
        )
    return {name: entry["value"] for name, entry in raw.items()}


def output(ctx: Context, name: str) -> str:
    """One output as a string, or a clean failure naming what is missing."""
    value = outputs(ctx).get(name)
    if value in (None, ""):
        raise die(
            f"Terraform has no output '{name}' for ENV={ctx.config.env} - apply it first"
        )
    return str(value)
