"""Initialize the Langfuse client used by the AgentCore runtime."""

import json
import os

import boto3
from langfuse import Langfuse, get_client
from opentelemetry.sdk.trace import TracerProvider


def init_langfuse_client() -> Langfuse:
    """Initialize the runtime's Langfuse client.

    Returns:
        A client using SSM-backed credentials when configured, or the environment-backed
        default client for local runs and tests.

    Raises:
        KeyError: If the configured SSM secret omits a required Langfuse credential.
        json.JSONDecodeError: If the configured SSM parameter is not valid JSON.
    """
    parameter_name = os.environ.get("LANGFUSE_SSM_PARAMETER_NAME")
    if not parameter_name:
        return get_client()

    parameter = boto3.client("ssm").get_parameter(
        Name=parameter_name,
        WithDecryption=True,
    )
    secret = json.loads(parameter["Parameter"]["Value"])
    return Langfuse(
        public_key=secret["publicKey"],
        secret_key=secret["secretKey"],
        base_url=os.environ.get("LANGFUSE_BASE_URL"),
        # AgentCore owns the global ADOT provider used by native evaluations. Keep
        # Langfuse's detailed application trace on its own provider so both exporters
        # can operate without replacing each other.
        tracer_provider=TracerProvider(),
    )
