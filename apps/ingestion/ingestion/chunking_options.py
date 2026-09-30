"""Choose how Bedrock chunks a document, per upload, for any kind of PDF.

Bedrock's Knowledge Base ingestion does the chunking; this module only decides *which* of its
strategies to ask for and validates the numbers. The default (``semantic``) suits flowing prose.
Other PDFs are better served differently, and the choice is made at upload time through S3 object
metadata (``x-amz-meta-chunking``, ``x-amz-meta-max-tokens``) so no code change is needed:

* ``semantic``     split where the meaning shifts (articles, manuals, reports) - the default
* ``hierarchical`` small child chunks for matching, larger parent chunks for context (long structured documents)
* ``fixed``        fixed-size windows with overlap (uniform text, logs, transcripts)
* ``none``         one chunk per page (slides, forms, invoices, tables of data)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

STRATEGIES = ("semantic", "hierarchical", "fixed", "none")
DEFAULT_STRATEGY = "semantic"
DEFAULT_MAX_TOKENS = 300
MIN_TOKENS, MAX_TOKENS = (
    50,
    1500,
)  # Bedrock accepts more; this range keeps chunks retrievable
OVERLAP_PERCENT = 10
PARENT_FACTOR = 5


@dataclass(frozen=True)
class ChunkingOptions:
    """A validated chunking choice.

    Attributes:
        strategy: One of ``STRATEGIES``.
        max_tokens: Target maximum tokens of a (child) chunk.
    """

    strategy: str = DEFAULT_STRATEGY
    max_tokens: int = DEFAULT_MAX_TOKENS

    def to_dict(self) -> dict:
        """Return a plain mapping for the registry."""
        return asdict(self)


def _int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def resolve_options(
    metadata: Mapping[str, str] | None = None, environ: Mapping[str, str] | None = None
) -> ChunkingOptions:
    """Combine an upload's metadata with the deployment defaults.

    Invalid values never fail an upload: they fall back to the default with a warning, so a typo
    cannot leave a PDF unindexed.

    Args:
        metadata: The S3 object's user metadata (keys are lower-case).
        environ: Environment providing ``CHUNKING_STRATEGY`` / ``CHUNK_MAX_TOKENS`` defaults.

    Returns:
        The options to build the data source with.
    """
    metadata = {k.lower(): v for k, v in (metadata or {}).items()}
    environ = os.environ if environ is None else environ
    strategy = (
        metadata.get("chunking") or environ.get("CHUNKING_STRATEGY") or DEFAULT_STRATEGY
    ).lower()
    if strategy not in STRATEGIES:
        logger.warning(
            "Unknown chunking strategy %r; using %s", strategy, DEFAULT_STRATEGY
        )
        strategy = DEFAULT_STRATEGY
    default_tokens = _int(environ.get("CHUNK_MAX_TOKENS"), DEFAULT_MAX_TOKENS)
    tokens = _int(metadata.get("max-tokens"), default_tokens)
    return ChunkingOptions(strategy, max(MIN_TOKENS, min(MAX_TOKENS, tokens)))


def to_bedrock(options: ChunkingOptions) -> dict:
    """Translate options into the data source's ``chunkingConfiguration``."""
    tokens = options.max_tokens
    if options.strategy == "semantic":
        return {
            "chunkingStrategy": "SEMANTIC",
            "semanticChunkingConfiguration": {
                "maxTokens": tokens,
                "bufferSize": 1,
                "breakpointPercentileThreshold": 95,
            },
        }
    if options.strategy == "hierarchical":
        return {
            "chunkingStrategy": "HIERARCHICAL",
            "hierarchicalChunkingConfiguration": {
                "levelConfigurations": [
                    {"maxTokens": min(tokens * PARENT_FACTOR, 8000)},
                    {"maxTokens": tokens},
                ],
                "overlapTokens": max(1, tokens * OVERLAP_PERCENT // 100),
            },
        }
    if options.strategy == "fixed":
        return {
            "chunkingStrategy": "FIXED_SIZE",
            "fixedSizeChunkingConfiguration": {
                "maxTokens": tokens,
                "overlapPercentage": OVERLAP_PERCENT,
            },
        }
    return {"chunkingStrategy": "NONE"}


def fingerprint(chunking: dict) -> str:
    """Return a short stable hash of a chunking configuration.

    It is stored in the data source description: Bedrock cannot change a data source's chunking
    after creation, so a differing fingerprint means the data source must be recreated.
    """
    return hashlib.sha1(json.dumps(chunking, sort_keys=True).encode()).hexdigest()[:12]
