"""Resolve the AgentCore Gateway endpoint used by evaluations."""

import os


def resolve_gateway_url() -> str:
    """Return the Gateway URL the experiments invoke.

    ``AGENT_GATEWAY_URL`` is set by ``docpipe experiments`` (from the Terraform ``gateway_url``
    output), by the staging workflow, or by hand (``http://localhost:8080`` targets a local
    ``make compose-up`` agent).

    Returns:
        The configured control-target base URL; ``/invocations`` is appended by the client.

    Raises:
        RuntimeError: If ``AGENT_GATEWAY_URL`` is not set.
    """
    url = os.environ.get("AGENT_GATEWAY_URL", "").strip()
    if not url:
        raise RuntimeError(
            "AGENT_GATEWAY_URL is not set - run through `make experiment-*`, or export the "
            "Terraform `gateway_url` output (http://localhost:8080 for a local agent)"
        )
    return url
