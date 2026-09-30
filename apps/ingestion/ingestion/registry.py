"""DynamoDB registry of ingested documents; it feeds the frontend's Knowledge Base dropdown."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PROCESSING = "PROCESSING"  # Textract is extracting
INDEXING = "INDEXING"  # Bedrock is chunking and embedding
READY = "READY"
FAILED = "FAILED"


class Registry:
    """Thin wrapper over the ``doc_id``-keyed registry table.

    Args:
        table: A boto3 DynamoDB ``Table`` resource.
    """

    def __init__(self, table) -> None:
        self._table = table

    def get(self, doc_id: str) -> dict[str, Any] | None:
        """Return the registry item for a document, or ``None``."""
        return self._table.get_item(Key={"doc_id": doc_id}).get("Item")

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        """Return every item currently in ``status`` (the table is small, so a filtered scan)."""
        from boto3.dynamodb.conditions import Attr

        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"FilterExpression": Attr("status").eq(status)}
        while True:
            page = self._table.scan(**kwargs)
            items.extend(page.get("Items", []))
            if not page.get("LastEvaluatedKey"):
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def update(self, doc_id: str, **fields: Any) -> None:
        """Create or merge attributes on a document's item and bump ``updated_at``."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        names = {f"#{key}": key for key in fields}
        values = {f":{key}": value for key, value in fields.items()}
        expression = "SET " + ", ".join(f"#{key} = :{key}" for key in fields)
        self._table.update_item(
            Key={"doc_id": doc_id},
            UpdateExpression=expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def delete(self, doc_id: str) -> None:
        """Remove a document's item."""
        self._table.delete_item(Key={"doc_id": doc_id})
