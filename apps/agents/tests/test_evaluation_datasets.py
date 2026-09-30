"""Test evaluation dataset definitions and item construction."""

import json

from base_dataset_creator import RAW_DATASETS_DIR, BaseDatasetCreator
from create_easy_dataset import EasyDatasetCreator
from create_guide_dataset import GuideDatasetCreator
from create_hard_dataset import HardDatasetCreator

_ALL = [EasyDatasetCreator, HardDatasetCreator, GuideDatasetCreator]
_EXPECTATIONS = {
    "expected_route",
    "expected_pages",
    "key_facts",
    "forbidden",
    "answerable",
    "required_steps",
    "min_sections",
    "max_retrievals",
    "follow_up",
}


def _raw(name):
    return json.loads((RAW_DATASETS_DIR / name).read_text())


def test_every_raw_file_is_well_formed():
    for creator_cls in _ALL:
        raw = _raw(creator_cls.source_file)
        assert raw["name"].startswith("evaluation/")
        ids = [item["id"] for item in raw["items"]]
        assert ids and len(ids) == len(set(ids)), creator_cls.source_file
        for item in raw["items"]:
            assert ("query" in item["input"]) != ("turns" in item["input"])
            assert "expected_output" in item
            assert set(item["metadata"]) <= _EXPECTATIONS, item["id"]


def test_datasets_do_not_depend_on_an_llm_judge():
    blob = json.dumps([_raw(c.source_file) for c in _ALL]).lower()

    assert "judge" not in blob and "rubric" not in blob


def test_each_dataset_targets_its_own_route_and_covers_abstention():
    for creator_cls, route in zip(_ALL, ["easy", "hard", "guide"]):
        items = _raw(creator_cls.source_file)["items"]
        routes = {i["metadata"].get("expected_route") for i in items} - {None}
        assert routes == {route}, creator_cls.source_file
        assert any(i["metadata"].get("answerable") is False for i in items)


def test_guide_items_declare_ordered_required_steps():
    for item in _raw(GuideDatasetCreator.source_file)["items"]:
        if item["metadata"].get("answerable") is False:
            continue
        assert len(item["metadata"]["required_steps"]) >= 2


def test_follow_up_items_use_multiple_turns_on_one_session():
    follow_ups = [
        i for i in _raw("easy.json")["items"] if i["metadata"].get("follow_up")
    ]

    assert follow_ups and all(len(i["input"]["turns"]) >= 2 for i in follow_ups)


def test_build_item_marks_items_active_and_merges_defaults():
    creator = BaseDatasetCreator.__new__(BaseDatasetCreator)
    creator.item_defaults = {"metadata": {"a": 1}}

    built = creator.build_item(
        {
            "id": "x",
            "input": {"query": "q"},
            "metadata": {"b": 2},
            "expected_output": "e",
        }
    )

    assert built == {
        "id": "x",
        "input": {"query": "q"},
        "metadata": {"a": 1, "b": 2},
        "status": "ACTIVE",
        "expected_output": "e",
    }
