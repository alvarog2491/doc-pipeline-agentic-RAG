import pytest

from scripts.pipeline_tools.commands.deploy import _validate_target_health
from scripts.pipeline_tools.ui import Failure


def test_target_health_allows_draining_targets_after_replacements_are_healthy() -> None:
    healthy = _validate_target_health(
        ["healthy", "draining", "healthy"], required_healthy=2
    )

    assert healthy == 2


def test_target_health_requires_enough_healthy_replacements() -> None:
    with pytest.raises(Failure, match="1/2 healthy"):
        _validate_target_health(["healthy", "draining"], required_healthy=2)


@pytest.mark.parametrize("state", ["initial", "unhealthy", "unused", "unavailable"])
def test_target_health_rejects_non_rollout_states(state: str) -> None:
    with pytest.raises(Failure, match=state):
        _validate_target_health(["healthy", "healthy", state], required_healthy=2)


def test_target_health_rejects_unhealthy_or_too_few_targets() -> None:
    with pytest.raises(Failure, match="non-healthy"):
        _validate_target_health(["healthy", "unhealthy"], required_healthy=1)
    with pytest.raises(Failure, match="only 1/2"):
        _validate_target_health(["healthy", "draining"], required_healthy=2)
