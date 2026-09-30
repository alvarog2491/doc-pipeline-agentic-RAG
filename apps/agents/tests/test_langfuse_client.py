"""Test Langfuse telemetry isolation from AgentCore's ADOT provider."""

import json

from opentelemetry.sdk.trace import TracerProvider

import langfuse_client


def test_ssm_client_uses_an_isolated_tracer_provider(monkeypatch):
    captured = {}

    class FakeSsm:
        def get_parameter(self, **kwargs):
            return {
                "Parameter": {
                    "Value": json.dumps(
                        {"publicKey": "pk-test", "secretKey": "sk-test"}
                    )
                }
            }

    monkeypatch.setenv("LANGFUSE_SSM_PARAMETER_NAME", "/test/langfuse")
    monkeypatch.setattr(langfuse_client.boto3, "client", lambda service: FakeSsm())
    monkeypatch.setattr(
        langfuse_client,
        "Langfuse",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    langfuse_client.init_langfuse_client()

    assert isinstance(captured["tracer_provider"], TracerProvider)
