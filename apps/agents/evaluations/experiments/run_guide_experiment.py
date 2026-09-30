"""Configure the guide-route regression experiment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base_experiment import BaseExperiment
from utils.logging_config import configure_logging

configure_logging()

# Minimum mean each deterministic score has to clear. Retune against a real run; the scores
# are computed from the run itself (no LLM judge), so they are stable between runs.
GUIDE_THRESHOLDS = {
    "route_accuracy": 0.80,
    "guide_step_coverage": 0.85,
    "guide_order_validity": 0.80,
    "guide_numbering": 0.80,
    "keyfact_recall": 0.80,
    "citation_validity": 0.90,
    "no_forbidden_claims": 1.00,
    "subagent_use": 1.00,
    "tool_budget": 1.00,
    "answer_well_formed": 1.00,
}


class GuideExperiment(BaseExperiment):
    """Run regression gates for the guide route."""

    dataset_name = "evaluation/guide-dataset"
    experiment_name = "Guide route baseline"
    experiment_description = "Invokes the deployed orchestrator on step-by-step requests; it must route to the guide path, extract sections with subagents and produce an ordered, numbered, cited procedure"
    thresholds = GUIDE_THRESHOLDS
    regression_message_prefix = "Guide experiment below threshold"


_EXPERIMENT = GuideExperiment()
experiment = _EXPERIMENT.experiment
main = _EXPERIMENT.main


if __name__ == "__main__":
    main()
