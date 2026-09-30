"""Configure the easy-route regression experiment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base_experiment import BaseExperiment
from utils.logging_config import configure_logging

configure_logging()

# Minimum mean each deterministic score has to clear. Retune against a real run; the scores
# are computed from the run itself (no LLM judge), so they are stable between runs.
EASY_THRESHOLDS = {
    "route_accuracy": 0.80,
    "retrieval_recall": 0.85,
    "keyfact_recall": 0.85,
    "citation_presence": 0.85,
    "citation_validity": 0.90,
    "abstention_correct": 0.80,
    "no_forbidden_claims": 1.00,
    "tool_budget": 1.00,
    "ttft_within_budget": 0.80,  # retuned from the first real run: 9 of 11 items were under 3.5 s, two hit model-latency spikes under 11 parallel requests
    "answer_well_formed": 1.00,
}


class EasyExperiment(BaseExperiment):
    """Run regression gates for the easy route."""

    dataset_name = "evaluation/easy-dataset"
    experiment_name = "Easy route baseline"
    experiment_description = "Invokes the deployed orchestrator (AGENT_GATEWAY_URL) on single-fact, follow-up, adversarial and unanswerable questions; it must route to the easy path, retrieve once, cite valid pages and state the right facts"
    thresholds = EASY_THRESHOLDS
    regression_message_prefix = "Easy experiment below threshold"


_EXPERIMENT = EasyExperiment()
experiment = _EXPERIMENT.experiment
main = _EXPERIMENT.main


if __name__ == "__main__":
    main()
