FROM python:3.12-slim

# Remove perl-base: not used by this app, and it carries unfixed CVEs
# (CVE-2026-13221, CVE-2026-57433, CVE-2026-12087) with no Debian trixie
# package available yet. It is Essential in Debian but has no reverse
# dependencies once installed, so removal is safe post-build.
RUN apt-get remove -y --purge --allow-remove-essential perl-base \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system app && useradd --system --gid app app

# Built from the repo root, where the uv workspace lockfile lives. The image installs
# exactly what uv.lock pins: --frozen skips re-resolution, so no member's pyproject.toml is
# needed here, and --package limits the install to this member's dependency closure. That
# the lockfile still matches the manifests is checked once per pipeline by `uv lock --check`
# (ci-feature.yml, cd-production.yml) rather than twice over inside two images. The member
# is a virtual uv project (package = false), so this installs dependencies only and the
# source below is run from the working directory - no second sync after it changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --package doc-pipeline-api

COPY --chown=app:app apps/api/chat_api/ apps/api/chat_api/

WORKDIR /app/apps/api

EXPOSE 8000
USER app
CMD ["uvicorn", "chat_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
