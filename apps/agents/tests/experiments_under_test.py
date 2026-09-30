"""A minimal concrete experiment for exercising ``BaseExperiment``."""

from base_experiment import BaseExperiment


def make_experiment(thresholds=None):
    class _Experiment(BaseExperiment):
        dataset_name = "evaluation/test"
        experiment_name = "test"
        experiment_description = "test"
        regression_message_prefix = "Test experiment below threshold"

    _Experiment.thresholds = thresholds or {}
    return _Experiment()
