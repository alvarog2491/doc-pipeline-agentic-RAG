FROM public.ecr.aws/docker/library/python:3.12-slim-trixie

# Remove perl-base: not used by the agent, and it carries unfixed Debian trixie CVEs
# (CVE-2026-13221, CVE-2026-57433, CVE-2026-12087). Nothing depends on it once installed.
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

# Installs exactly what the root uv.lock pins for this member. `uv lock --check` runs in CI,
# so the image does not re-validate the lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --package DocPipelineAgent

COPY --chown=bedrock_agentcore:bedrock_agentcore apps/agents/ apps/agents/

# Run from the app directory so top-level imports (`from graph import ...`) resolve.
WORKDIR /app/apps/agents

USER bedrock_agentcore

# AgentCore Runtime expects HTTP on 8080 (8000 is MCP, 9000 is A2A).
EXPOSE 8080

# AgentCore supplies the ADOT provider used by native online evaluations. Langfuse uses
# an isolated provider in langfuse_client.py so both telemetry destinations remain active.
CMD ["opentelemetry-instrument", "python", "-m", "main"]
