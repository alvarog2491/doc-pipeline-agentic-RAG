"""Test Bedrock chat-model configuration and validation."""

from unittest.mock import ANY, patch

import pytest


def test_load_model_raises_when_model_id_is_absent(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    from model.load import load_model

    with pytest.raises(KeyError):
        load_model()


def test_load_model_constructs_chat_bedrock_with_env_config(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_TEMPERATURE", raising=False)

    with patch("model.load.ChatBedrockConverse") as mock_cls:
        from model.load import load_model

        load_model()

    mock_cls.assert_called_once_with(
        model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        region_name="eu-central-1",
        temperature=0.0,
        output_version="v1",
        config=ANY,
    )


def test_load_model_treats_empty_temperature_as_default(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_TEMPERATURE", "")  # docker-compose passes "" when unset

    with patch("model.load.ChatBedrockConverse") as mock_cls:
        from model.load import load_model

        load_model()

    assert mock_cls.call_args.kwargs["temperature"] == 0.0


def test_load_model_reads_temperature_from_env(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_TEMPERATURE", "0.7")

    with patch("model.load.ChatBedrockConverse") as mock_cls:
        from model.load import load_model

        load_model()

    mock_cls.assert_called_once_with(
        model_id="amazon.nova-pro-v1:0",
        region_name="us-east-1",
        temperature=0.7,
        output_version="v1",
        config=ANY,
    )


def test_load_model_falls_back_to_default_region(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("BEDROCK_TEMPERATURE", raising=False)

    with patch("model.load.ChatBedrockConverse") as mock_cls:
        from model.load import load_model

        load_model()

    mock_cls.assert_called_once_with(
        model_id="amazon.nova-pro-v1:0",
        region_name="us-east-1",
        temperature=0.0,
        output_version="v1",
        config=ANY,
    )
