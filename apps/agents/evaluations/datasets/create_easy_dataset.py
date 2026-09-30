"""Upsert the easy-route evaluation dataset."""

from base_dataset_creator import BaseDatasetCreator, run_creator


class EasyDatasetCreator(BaseDatasetCreator):
    """Create the easy-route dataset."""

    source_file = "easy.json"


if __name__ == "__main__":
    run_creator(EasyDatasetCreator)
