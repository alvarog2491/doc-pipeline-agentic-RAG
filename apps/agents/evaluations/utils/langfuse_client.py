"""Initialize Langfuse clients for evaluation scripts."""

import json
import os

import boto3
from langfuse import Langfuse, get_client


def init_langfuse_client() -> Langfuse:
    """Initialize an evaluation Langfuse client.

    Returns:
        A client using SSM-backed credentials when configured, or the environment-backed
        default client when the parameter name is explicitly disabled.

    Raises:
        KeyError: If the configured SSM secret omits a required credential.
        json.JSONDecodeError: If the configured SSM parameter is not valid JSON.
    """
    parameter_name = os.environ.get(
        "LANGFUSE_SSM_PARAMETER_NAME", "/doc-pipeline-agent/dev/langfuse"
    )
    if not parameter_name:
        return get_client()

    parameter = boto3.client("ssm").get_parameter(
        Name=parameter_name, WithDecryption=True
    )
    secret = json.loads(parameter["Parameter"]["Value"])
    return Langfuse(
        public_key=secret["publicKey"],
        secret_key=secret["secretKey"],
        base_url=os.environ.get("LANGFUSE_BASE_URL"),
    )
