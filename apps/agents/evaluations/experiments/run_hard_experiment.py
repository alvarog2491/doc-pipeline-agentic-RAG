"""Configure the hard-route regression experiment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base_experiment import BaseExperiment
from utils.logging_config import configure_logging

configure_logging()

# Minimum mean each deterministic score has to clear. Retune against a real run; the scores
# are computed from the run itself (no LLM judge), so they are stable between runs.
HARD_THRESHOLDS = {
    "route_accuracy": 0.70,
    "retrieval_recall": 0.80,
    "keyfact_recall": 0.75,
    "citation_validity": 0.90,
    "abstention_correct": 0.70,
    "no_forbidden_claims": 1.00,
    "subagent_use": 1.00,
    "tool_budget": 1.00,
    "ttft_within_budget": 0.80,
    "answer_well_formed": 1.00,
}


class HardExperiment(BaseExperiment):
    """Run regression gates for the hard route."""

    dataset_name = "evaluation/hard-dataset"
    experiment_name = "Hard route baseline"
    experiment_description = "Invokes the deployed orchestrator on multi-part and cross-section questions; it must route to the hard path, retrieve across the relevant pages and combine the facts with valid citations"
    thresholds = HARD_THRESHOLDS
    regression_message_prefix = "Hard experiment below threshold"


_EXPERIMENT = HardExperiment()
experiment = _EXPERIMENT.experiment
main = _EXPERIMENT.main


if __name__ == "__main__":
    main()
