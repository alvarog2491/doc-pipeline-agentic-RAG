"""Build Langfuse datasets from version-controlled JSON definitions."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.langfuse_client import init_langfuse_client
from utils.logging_config import configure_logging

logger = logging.getLogger(__name__)

RAW_DATASETS_DIR = Path(__file__).resolve().parent / "raw_datasets"


class BaseDatasetCreator:
    """Load and upsert one evaluation dataset.

    Subclasses set ``source_file`` to a JSON definition under ``raw_datasets``. Item-level
    metadata overrides dataset defaults, and stable identifiers make repeated runs
    idempotent.
    """

    #: File name under ``raw_datasets/``.
    source_file: str

    def __init__(self) -> None:
        raw = json.loads((RAW_DATASETS_DIR / self.source_file).read_text())
        self.dataset_name: str = raw["name"]
        self.description: str = raw["description"]
        self.item_defaults: dict = raw.get("item_defaults", {})
        self.raw_items: list[dict] = raw["items"]

    def build_item(self, raw_item: dict) -> dict:
        """Build Langfuse item arguments from a raw dataset item.

        Args:
            raw_item: Dataset item containing an identifier, input, optional expected output,
                and optional metadata.

        Returns:
            Keyword arguments for ``create_dataset_item`` with default and item metadata
            merged.
        """
        metadata = {
            **self.item_defaults.get("metadata", {}),
            **raw_item.get("metadata", {}),
        }
        kwargs: dict = {
            "id": raw_item["id"],
            "input": raw_item["input"],
            "metadata": metadata,
            # Re-listing an id the definition had dropped restores it from ARCHIVED.
            "status": "ACTIVE",
        }
        if "expected_output" in raw_item:
            kwargs["expected_output"] = raw_item["expected_output"]
        return kwargs

    def _ensure_dataset(self, langfuse) -> None:
        """Ensure the configured dataset exists.

        ``POST /datasets`` upserts by name, so this creates the dataset on the first run
        and refreshes its description on later ones.
        """
        langfuse.create_dataset(name=self.dataset_name, description=self.description)
        logger.info("Ensured dataset '%s'", self.dataset_name)

    def _archive_stale_items(self, langfuse) -> list[str]:
        """Archive active Langfuse items the definition no longer lists.

        Args:
            langfuse: Authenticated Langfuse client.

        Returns:
            The ids that were archived.
        """
        configured_ids = {raw_item["id"] for raw_item in self.raw_items}
        stale = [
            item
            for item in langfuse.get_dataset(self.dataset_name).items
            if item.id not in configured_ids
        ]
        for item in stale:
            # No hard delete: archiving keeps the item out of experiment runs while
            # preserving its history in past dataset runs.
            langfuse.create_dataset_item(
                dataset_name=self.dataset_name,
                id=item.id,
                input=item.input,
                expected_output=item.expected_output,
                metadata=item.metadata,
                status="ARCHIVED",
            )
        return [item.id for item in stale]

    def run(self) -> None:
        """Sync the Langfuse dataset to match the version-controlled definition.

        Upserts every configured item, then archives any still-active item the definition
        no longer lists, so experiment runs see exactly the version-controlled set.
        """
        langfuse = init_langfuse_client()
        self._ensure_dataset(langfuse)
        for raw_item in self.raw_items:
            langfuse.create_dataset_item(
                dataset_name=self.dataset_name, **self.build_item(raw_item)
            )
        archived = self._archive_stale_items(langfuse)
        logger.info(
            "Synced '%s': %d item(s) upserted, %d archived%s",
            self.dataset_name,
            len(self.raw_items),
            len(archived),
            f" ({', '.join(archived)})" if archived else "",
        )


def run_creator(creator_cls: type[BaseDatasetCreator]) -> None:
    """Run a dataset creator from a script entrypoint.

    Args:
        creator_cls: Dataset creator class to instantiate and run.
    """
    configure_logging()
    load_dotenv()
    creator_cls().run()
