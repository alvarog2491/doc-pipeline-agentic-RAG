"""Environment-derived configuration shared by the ingestion Lambda handlers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

UPLOAD_PREFIX = "uploads/"
EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class Settings:
    """Resolved Lambda configuration.

    Attributes:
        env: Deployment environment name, used to namespace Knowledge Base names.
        registry_table: DynamoDB table listing every document and its Knowledge Base.
        vector_bucket: S3 Vectors bucket that holds one index per document.
        kb_role_arn: Service role Bedrock assumes to embed and query each Knowledge Base.
        embedding_model_id: Titan embedding model the Knowledge Bases embed chunks and queries with.
        textract_topic_arn: SNS topic Textract publishes job completion to.
        textract_role_arn: Role Textract assumes to publish to that topic.
    """

    env: str
    registry_table: str
    vector_bucket: str
    kb_role_arn: str
    embedding_model_id: str
    textract_topic_arn: str
    textract_role_arn: str

    @classmethod
    def from_env(cls) -> Settings:
        """Read every setting from the process environment.

        Returns:
            Settings populated from the variables Terraform sets on the Lambda.

        Raises:
            KeyError: If a required variable is missing.
        """
        return cls(
            env=os.environ["ENV"],
            registry_table=os.environ["REGISTRY_TABLE"],
            vector_bucket=os.environ["VECTOR_BUCKET"],
            kb_role_arn=os.environ["KB_ROLE_ARN"],
            embedding_model_id=os.environ.get(
                "EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
            ),
            textract_topic_arn=os.environ["TEXTRACT_TOPIC_ARN"],
            textract_role_arn=os.environ["TEXTRACT_ROLE_ARN"],
        )


def slugify(value: str) -> str:
    """Return a lowercase, dash-separated slug safe for AWS resource names."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "document"
