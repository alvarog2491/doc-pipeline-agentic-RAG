# /// script
# requires-python = ">=3.12"
# dependencies = ["langfuse>=4.15.1", "pyyaml"]
# ///
import glob
import os
import subprocess
import sys

import yaml
from langfuse import get_client
from langfuse.api import NotFoundError

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PROMPTS_DIR = os.path.join(REPO_ROOT, "apps", "agents", "prompts")


def prompt_label() -> str:
    """The Langfuse label to publish under - this environment's, and only this one's.

    Required rather than defaulted. Every label here is one an environment's agent reads
    at startup, so guessing wrong does not fail, it silently republishes the prompts some
    other environment is serving. There is no default that is safe to be wrong about, so
    there is no default: `docpipe prompts sync` passes it, derived from ENV.
    """
    label = os.environ.get("PROMPT_LABEL", "").strip()
    if not label:
        print(
            "PROMPT_LABEL is not set - run this through `docpipe prompts sync`, which "
            "derives it from ENV (scripts/pipeline_tools/config.py)",
            file=sys.stderr,
        )
        sys.exit(1)
    return label


def load_prompt_file(path: str) -> list[dict]:
    with open(path) as f:
        doc = yaml.safe_load(f)
    messages = []
    for msg in doc["messages"]:
        if "placeholder" in msg:
            messages.append({"type": "placeholder", "name": msg["placeholder"]})
        else:
            messages.append(
                {"type": "chatmessage", "role": msg["role"], "content": msg["content"]}
            )
    return messages


def git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()


def main() -> None:
    paths = sorted(glob.glob(os.path.join(PROMPTS_DIR, "*.yaml")))
    if not paths:
        print(f"No prompt files found in {PROMPTS_DIR}", file=sys.stderr)
        sys.exit(1)

    # Resolved before the client is built, so a missing label fails on its own message
    # rather than behind a Langfuse authentication error that is not the actual problem.
    label = prompt_label()
    lf = get_client()
    sha = git_sha()
    github_sha = os.environ.get("GITHUB_SHA")
    tags = [github_sha] if github_sha else None
    print(f"Publishing {len(paths)} prompt(s) under label '{label}'", file=sys.stderr)

    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        messages = load_prompt_file(path)

        # Compared against this label's current version, not a shared one: "unchanged"
        # has to mean "unchanged for this environment", or the first sync into a new
        # environment would skip every prompt that happened to match another one's and
        # leave the label pointing at nothing.
        try:
            current = lf.get_prompt(name, type="chat", label=label, cache_ttl_seconds=0)
            unchanged = current.prompt == messages
        except NotFoundError:
            unchanged = False

        if unchanged:
            print(f"{name}: unchanged (v{current.version})")
            continue

        created = lf.create_prompt(
            name=name,
            prompt=messages,
            type="chat",
            labels=[label],
            tags=tags,
            commit_message=f"sync from {sha}",
        )
        print(f"{name}: synced -> v{created.version} [{label}]")


if __name__ == "__main__":
    main()
