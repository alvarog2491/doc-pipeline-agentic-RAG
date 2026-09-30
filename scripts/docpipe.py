#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     # Every AWS call in this repository's tooling goes through boto3 rather than the AWS
#     # CLI. The floor is the version already verified against the AgentCore control-plane
#     # calls in these commands.
#     "boto3>=1.43.83",
#     # The deployment smoke test speaks the same streaming HTTP contract as
#     # apps/agents/evaluations/agent_client.py, which is httpx.
#     "httpx>=0.27",
# ]
# ///
"""Entry point for every task this repository automates.

    uv run scripts/docpipe.py --help

The inline metadata above is the whole dependency story: `uv run` resolves it into an
ephemeral environment and ignores the uv workspace at the repository root, so this CLI
never shares a resolution with apps/agents or apps/api and no call site has to
repeat a `--with` flag. The heavier tools it drives - Langfuse, the agent's experiments -
stay in their own scripts and workspace environments, run as subprocesses, so a
deploy does not pay to install them.

The Makefile and .github/workflows/ are the callers; see scripts/README.md.
"""

import sys
from pathlib import Path

# Run as a file, so sys.path[0] is already scripts/ - but only when uv invokes it that
# way. Making it explicit means `python scripts/docpipe.py` from anywhere behaves the same.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_tools.cli import main

if __name__ == "__main__":
    main()
