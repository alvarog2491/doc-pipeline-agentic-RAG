"""Load the Bedrock chat model used by the conversational graph."""

import logging
import os

from botocore.config import Config
from langchain_aws import ChatBedrockConverse

logger = logging.getLogger(__name__)

# get_model() in main.py caches one ChatBedrockConverse for the whole process, so every
# concurrent session's LLM calls share its boto3 client. Botocore's default pool (10) is
# sized for one caller at a time; past that, urllib3 discards returned connections instead
# of reusing them, forcing a fresh TLS handshake per call under concurrent load.
_MAX_POOL_CONNECTIONS = 50

# Sampling temperature when BEDROCK_TEMPERATURE is not set. Every deploy and every local
# run supplies it from the one value in terraform/defaults.json (via terraform/config.tf or
# scripts/pipeline_tools/config.py); this literal is only the fallback for a bare
# `python main.py`. Shared by every model client the orchestrator builds.
_DEFAULT_TEMPERATURE = 0.0


def load_model(model_id_env: str = "BEDROCK_MODEL_ID") -> ChatBedrockConverse:
    """Create a Bedrock Converse chat-model client.

    Args:
        model_id_env: Environment variable holding the model id; the router uses
            ``BEDROCK_ROUTER_MODEL_ID`` to pick a smaller model.

    Returns:
        A client configured from ``model_id_env``, the active AWS region, and
        ``BEDROCK_TEMPERATURE`` (default ``0.0``).

    Raises:
        KeyError: If the model identifier or AWS region is not configured.
        ValueError: If ``BEDROCK_TEMPERATURE`` is set but is not a number.
    """
    model_id = os.environ[model_id_env]
    region = os.environ.get("AWS_REGION") or os.environ["AWS_DEFAULT_REGION"]
    temperature = float(os.environ.get("BEDROCK_TEMPERATURE") or _DEFAULT_TEMPERATURE)

    logger.info(
        "Loading Bedrock model model_id=%s region=%s temperature=%s",
        model_id,
        region,
        temperature,
    )
    return ChatBedrockConverse(
        model_id=model_id,
        region_name=region,
        temperature=temperature,
        output_version="v1",
        config=Config(max_pool_connections=_MAX_POOL_CONNECTIONS),
    )
