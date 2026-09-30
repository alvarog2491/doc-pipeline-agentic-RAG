"""Personal dev deploys, the destroy that undoes them, and the post-deploy verification.

Staging and production are deployed exclusively by .github/workflows/, so every command
that mutates infrastructure calls `refuse_managed` before it touches anything.

The Langfuse credentials in SSM are NOT bootstrapped here - that is a manual, one-time
step per environment (README "First-time bootstrap"), so it never runs on every deploy and
is never touched by `terraform destroy`.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import httpx
from botocore.exceptions import WaiterError

from .. import github, terraform
from ..aws import aws_call
from ..context import Context
from ..shell import REPO_ROOT, confirm, is_tty, require, run
from ..ui import Stages, die, info
from . import agent, prompts

HEALTH_ATTEMPTS = 10
HEALTH_RETRY_SECONDS = 10


def _build_and_push(
    ctx: Context, platform: str, dockerfile: str, images: Sequence[str]
) -> None:
    """Build once, publish the same image under every tag given.

    The build context is the repository root, where the uv workspace lockfile both Python
    images install from lives.
    """
    tag_args = [arg for image in images for arg in ("-t", image)]
    env = ctx.child_env()
    run(
        [
            "docker",
            "build",
            "--platform",
            platform,
            "-f",
            dockerfile,
            *tag_args,
            str(REPO_ROOT),
        ],
        env=env,
        cwd=REPO_ROOT,
    )
    for image in images:
        run(["docker", "push", image], env=env, cwd=REPO_ROOT)


def deploy(ctx: Context) -> None:
    """Full personal dev deploy: repositories, both images, every resource, ECS rollout."""
    ctx.refuse_managed()
    require("docker", "uv", "terraform")
    progress = Stages(6)

    progress.stage("Preflight: required tools & credentials")
    ctx.load_dotenv()
    ctx.refuse_managed()  # .env may have changed ENV out from under the first check.
    registry = ctx.aws.ecr_registry()
    config = ctx.config
    agent_image = f"{registry}/{config.agent_ecr_repository}:{config.image_tag}"
    api_image = f"{registry}/{config.api_ecr_repository}:{config.image_tag}"

    progress.stage("Prompts: sync prompt sources to Langfuse")
    prompts.sync(ctx)

    progress.stage("Terraform: ensure the ECR repositories exist")
    terraform.apply(ctx, targets=["module.ecr"])

    progress.stage("Docker: log in to ECR and push both images")
    run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        env=ctx.child_env(),
        cwd=REPO_ROOT,
        stdin=ctx.aws.ecr_login_password(),
    )
    _build_and_push(ctx, "linux/arm64", "apps/agents/Dockerfile", [agent_image])
    _build_and_push(ctx, "linux/amd64", "apps/api/Dockerfile", [api_image])

    progress.stage("Terraform: apply every module")
    terraform.apply(
        ctx,
        {
            "agent_image_tag": config.image_tag,
            "api_image_tag": config.image_tag,
            "langfuse_base_url": config.langfuse_base_url,
            # dev keeps the API at zero tasks by default; a personal deploy wants it running.
            "ecs_desired_count": "1",
        },
    )

    progress.stage("Outputs")
    outputs = terraform.outputs(ctx)
    progress.done()
    info(f"Agent image  {agent_image}")
    info(f"API image    {api_image}")
    info(
        f"Upload PDFs to s3://{outputs['documents_bucket']}/uploads/  (or `make upload-document PDF=file.pdf`)"
    )
    info(f"API          https://{outputs['cloudfront_domain']}  (VITE_API_URL)")


def destroy(ctx: Context, *, assume_yes: bool = False) -> None:
    """Destroy every resource in this environment, after a typed confirmation.

    The manually bootstrapped Langfuse credentials survive: Terraform only references them
    by name, so it can never delete them.
    """
    ctx.refuse_managed()
    if not assume_yes:
        if not is_tty():
            raise die(
                "refusing to destroy without a terminal to confirm on - pass --yes"
            )
        prompt = (
            f"This will destroy every doc-pipeline-{ctx.config.env} resource "
            "(including uploaded documents and their Knowledge Bases). Continue? [y/N] "
        )
        if not confirm(prompt):
            raise die("aborted.")
    terraform.destroy(ctx)


def outputs(ctx: Context) -> None:
    """Print the environment's Terraform outputs as ``key=value`` lines for $GITHUB_OUTPUT."""
    values = terraform.outputs(ctx)
    for name, value in sorted(values.items()):
        if isinstance(value, (str, int, float, bool)):
            print(f"{name}={value}")
            github.output(name, str(value))


def _validate_target_health(states: list[str], required_healthy: int) -> int:
    """Require serving targets while tolerating old targets that are draining.

    Args:
        states: Current ALB target health states.
        required_healthy: Minimum number of targets that must be healthy.

    Returns:
        The number of healthy targets.

    Raises:
        Failure: If too few targets are healthy or any target is in a state other
            than ``healthy`` or ``draining``.
    """
    healthy = states.count("healthy")
    blocking = [state for state in states if state not in {"healthy", "draining"}]
    if blocking:
        raise die(f"target group has non-healthy targets: {', '.join(blocking)}")
    if healthy < required_healthy:
        raise die(
            f"target group has only {healthy}/{required_healthy} healthy targets "
            "while old targets are draining"
        )
    return healthy


def _describe_service(ctx: Context, cluster: str, service_name: str) -> dict:
    with aws_call(f"cannot read ECS service '{service_name}'"):
        services = ctx.aws.client("ecs").describe_services(
            cluster=cluster, services=[service_name]
        )["services"]
    return services[0] if services else {}


def _wait_for(url: str, description: str) -> None:
    """Retry a GET until it answers; a target can pass its own check just before routing starts."""
    for attempt in range(1, HEALTH_ATTEMPTS + 1):
        try:
            if httpx.get(url, timeout=10.0).status_code < 400:
                info(f"  {url} -> 200")
                return
        except httpx.HTTPError:
            pass
        if attempt == HEALTH_ATTEMPTS:
            raise die(f"{description} ({url}) did not answer after {attempt} attempts")
        info(f"  {description} not answering yet (attempt {attempt}), retrying...")
        time.sleep(HEALTH_RETRY_SECONDS)


def verify(ctx: Context) -> None:
    """Assert a freshly deployed environment actually serves traffic.

    A successful `terraform apply` only means AWS accepted the change. It does not mean a
    task started, passed its health check and registered with the load balancer, that the
    REST + SSE API answers through CloudFront, or that the agent behind the Gateway
    responds. Each check below is one way a deploy can be green while the service is down.
    """
    tf = terraform.outputs(ctx)
    cluster, service_name = str(tf["cluster_name"]), str(tf["service_name"])
    progress = Stages(5)

    progress.stage("ECS: the service exists and wants tasks")
    service = _describe_service(ctx, cluster, service_name)
    if service.get("status") != "ACTIVE":
        raise die(f"ECS service '{service_name}' is not ACTIVE in cluster '{cluster}'")
    desired = service.get("desiredCount", 0)
    # A zero-task service is "stable" to the waiter, so it would sail through every check
    # below while serving nothing at all.
    if desired <= 0:
        raise die(
            f"ECS service '{service_name}' has desiredCount=0 - deployed but serving nothing"
        )
    info(f"  desiredCount={desired}")

    progress.stage("ECS: wait for the rollout to settle")
    try:
        ctx.aws.client("ecs").get_waiter("services_stable").wait(
            cluster=cluster, services=[service_name]
        )
    except WaiterError as error:
        raise die(
            f"ECS service '{service_name}' did not stabilise - check events and task logs ({error})"
        ) from error
    service = _describe_service(ctx, cluster, service_name)
    running = service.get("runningCount", 0)
    if running != desired:
        raise die(f"ECS service '{service_name}' has {running}/{desired} tasks running")
    # A rolled-back deployment is still "stable", so assert the rollout that ran survived.
    if any(d.get("rolloutState") == "FAILED" for d in service.get("deployments", [])):
        raise die(
            f"ECS service '{service_name}' has a FAILED deployment - the circuit breaker rolled it back"
        )
    info(
        f"  {running}/{desired} tasks running on {str(service.get('taskDefinition', '')).rsplit('/', 1)[-1]}"
    )

    progress.stage("ALB: enough targets are healthy")
    load_balancers = service.get("loadBalancers") or []
    target_group_arn = (
        load_balancers[0].get("targetGroupArn") if load_balancers else None
    )
    if not target_group_arn:
        raise die(f"ECS service '{service_name}' is not attached to a target group")
    with aws_call(f"cannot read target health for '{target_group_arn}'"):
        health = ctx.aws.client("elbv2").describe_target_health(
            TargetGroupArn=target_group_arn
        )["TargetHealthDescriptions"]
    states = [description["TargetHealth"]["State"] for description in health]
    healthy = _validate_target_health(states, required_healthy=desired)
    info(f"  {healthy} target(s) healthy")

    progress.stage("CloudFront: the REST API answers over HTTPS")
    domain = str(tf["cloudfront_domain"])
    _wait_for(f"https://{domain}/health", "/health")
    _wait_for(f"https://{domain}/v1/knowledge-bases", "/v1/knowledge-bases")

    progress.stage("AgentCore: the agent answers through the Gateway")
    agent.smoke_test(ctx)

    progress.done()
    info(
        f"ENV={ctx.config.env} verified: ECS serving {running} task(s), API and agent answering"
    )
