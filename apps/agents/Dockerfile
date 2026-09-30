FROM public.ecr.aws/docker/library/python:3.12-slim-trixie

# Security Hardening: Purge unused essential package to mitigate unfixed Debian trixie CVEs
# (CVE-2026-13221, CVE-2026-57433, CVE-2026-12087). Safe post-build removal (no reverse dependencies).
RUN apt-get remove -y --purge --allow-remove-essential perl-base \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

ARG UV_DEFAULT_INDEX
ARG UV_INDEX

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} \
    UV_INDEX=${UV_INDEX} \
    PATH="/app/.venv/bin:$PATH"

RUN useradd -m -u 1000 bedrock_agentcore

# Workspace Installation: Resolves dependency closure from root workspace lockfile (uv.lock).
# Uses `--frozen` for strict, immutable installation and `--package` to isolate target member requirements.
# Manifest drift validation (`uv lock --check`) is enforced upstream in CI/CD.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --package DocPipelineAgent

COPY --chown=bedrock_agentcore:bedrock_agentcore apps/agents/ apps/agents/

# Execution Context: Set root directory to resolve top-level agent imports (`from graph import ...`)
WORKDIR /app/apps/agents

USER bedrock_agentcore

# AWS Bedrock AgentCore Runtime Service Contract Ports:
# 8080: HTTP Mode | 8000: MCP Mode | 9000: A2A Mode
EXPOSE 8080

# AgentCore supplies the ADOT provider used by native online evaluations. Langfuse uses
# an isolated provider in langfuse_client.py so both telemetry destinations remain active.
CMD ["opentelemetry-instrument", "python", "-m", "main"]
