"""The AWS surface: one session, one place the region and profile are applied.

An empty AWS_PROFILE means "use the credentials already in the environment", which is the
CI case: GitHub OIDC exports them as environment variables and writes no ~/.aws/config,
so an exported-but-empty AWS_PROFILE fails with "The config profile could not be found" -
in boto3 exactly as in the AWS CLI. `apply_environment` therefore *removes* the variable
rather than passing an empty one, which fixes it for this process and for every
subprocess that inherits from it (terraform, docker, pnpm, the uv-run scripts) in one move.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import Config
from .ui import die


def apply_environment(config: Config) -> None:
    """Normalise AWS_REGION / AWS_PROFILE for this process and everything it spawns."""
    os.environ["AWS_REGION"] = config.region
    if config.profile:
        os.environ["AWS_PROFILE"] = config.profile
    else:
        os.environ.pop("AWS_PROFILE", None)


@contextmanager
def aws_call(action: str) -> Iterator[None]:
    """Turn a boto3 call's `ClientError`/`BotoCoreError` into a clean `Failure`.

    Every AWS call a command makes directly (rather than through one of the `Aws` helper
    methods below, which already do this) should be wrapped in `with aws_call("..."):` -
    an expired local credential or a throttled call is the single most common way any of
    these commands fails, and it deserves the same `ERROR: <message>` reporting every
    other failure in this CLI gets, not a raw botocore traceback.
    """
    try:
        yield
    except (ClientError, BotoCoreError) as error:
        raise die(f"{action}: {error}") from error


class Aws:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = boto3.Session(
            profile_name=config.profile or None, region_name=config.region
        )

    def client(self, service: str):
        return self.session.client(service)

    def account_id(self) -> str:
        with aws_call("cannot resolve the AWS account id (check your credentials)"):
            return self.client("sts").get_caller_identity()["Account"]

    def ecr_registry(self) -> str:
        return f"{self.account_id()}.dkr.ecr.{self.config.region}.amazonaws.com"

    def ssm_parameter(self, name: str) -> str:
        try:
            response = self.client("ssm").get_parameter(Name=name, WithDecryption=True)
        except (ClientError, BotoCoreError) as error:
            raise die(
                f"cannot read {name} - see README.md 'First-time bootstrap' ({error})"
            ) from error
        return response["Parameter"]["Value"]

    def ecr_login_password(self) -> str:
        """What `aws ecr get-login-password` prints, for `docker login --password-stdin`."""
        with aws_call("cannot get an ECR login token"):
            token = self.client("ecr").get_authorization_token()["authorizationData"][
                0
            ]["authorizationToken"]
        return base64.b64decode(token).decode().split(":", 1)[1]
