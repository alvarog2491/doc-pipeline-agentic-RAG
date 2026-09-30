import pytest
from ingestion.chunking_options import (
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS,
    MIN_TOKENS,
    ChunkingOptions,
    fingerprint,
    resolve_options,
    to_bedrock,
)


def test_defaults_to_semantic_chunking_for_any_pdf():
    assert resolve_options({}, {}) == ChunkingOptions("semantic", DEFAULT_MAX_TOKENS)


def test_upload_metadata_beats_deployment_defaults():
    options = resolve_options(
        {"chunking": "Fixed", "max-tokens": "200"}, {"CHUNKING_STRATEGY": "none"}
    )

    assert options == ChunkingOptions("fixed", 200)


def test_deployment_defaults_apply_when_the_upload_says_nothing():
    options = resolve_options(
        {}, {"CHUNKING_STRATEGY": "hierarchical", "CHUNK_MAX_TOKENS": "400"}
    )

    assert options == ChunkingOptions("hierarchical", 400)


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"chunking": "banana"}, ChunkingOptions("semantic", DEFAULT_MAX_TOKENS)),
        ({"max-tokens": "lots"}, ChunkingOptions("semantic", DEFAULT_MAX_TOKENS)),
        ({"max-tokens": "1"}, ChunkingOptions("semantic", MIN_TOKENS)),
        ({"max-tokens": "999999"}, ChunkingOptions("semantic", MAX_TOKENS)),
    ],
)
def test_bad_values_never_fail_an_upload(metadata, expected):
    assert resolve_options(metadata, {}) == expected


def test_each_strategy_maps_to_bedrocks_chunking_configuration():
    semantic = to_bedrock(ChunkingOptions("semantic", 300))
    hierarchical = to_bedrock(ChunkingOptions("hierarchical", 300))
    fixed = to_bedrock(ChunkingOptions("fixed", 300))

    assert semantic["chunkingStrategy"] == "SEMANTIC"
    assert semantic["semanticChunkingConfiguration"]["maxTokens"] == 300
    assert hierarchical["chunkingStrategy"] == "HIERARCHICAL"
    levels = hierarchical["hierarchicalChunkingConfiguration"]["levelConfigurations"]
    assert [level["maxTokens"] for level in levels] == [
        1500,
        300,
    ]  # parent first, then child
    assert fixed["fixedSizeChunkingConfiguration"] == {
        "maxTokens": 300,
        "overlapPercentage": 10,
    }
    assert to_bedrock(ChunkingOptions("none")) == {"chunkingStrategy": "NONE"}


def test_fingerprint_changes_with_the_configuration_only():
    a, b = (
        to_bedrock(ChunkingOptions("fixed", 200)),
        to_bedrock(ChunkingOptions("fixed", 200)),
    )

    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(to_bedrock(ChunkingOptions("fixed", 250)))
