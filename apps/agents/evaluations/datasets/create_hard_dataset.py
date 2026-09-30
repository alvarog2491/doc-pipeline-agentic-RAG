"""Upsert the hard-route evaluation dataset."""

from base_dataset_creator import BaseDatasetCreator, run_creator


class HardDatasetCreator(BaseDatasetCreator):
    """Create the hard-route dataset."""

    source_file = "hard.json"


if __name__ == "__main__":
    run_creator(HardDatasetCreator)
