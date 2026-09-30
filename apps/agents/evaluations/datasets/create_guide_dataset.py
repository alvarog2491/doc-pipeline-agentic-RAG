"""Upsert the guide-route evaluation dataset."""

from base_dataset_creator import BaseDatasetCreator, run_creator


class GuideDatasetCreator(BaseDatasetCreator):
    """Create the guide-route dataset."""

    source_file = "guide.json"


if __name__ == "__main__":
    run_creator(GuideDatasetCreator)
