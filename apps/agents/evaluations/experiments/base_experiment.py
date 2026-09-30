"""Run a dataset experiment against the deployed agent and enforce deterministic score gates."""

import itertools
import logging
import os
import sys
import uuid
from abc import ABC
from pathlib import Path

from dotenv import load_dotenv
from langfuse import RegressionError, RunnerContext

load_dotenv()

EVALUATIONS_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATIONS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATIONS_ROOT))

from agent_client import invoke_agent
from errors import ExperimentItemsFailedError, install_langfuse_item_error_logging
from evaluators.scorers import score_run
from utils.langfuse_client import init_langfuse_client
from utils.thresholds import check_regressions

logger = logging.getLogger(__name__)

# Make Langfuse's terse "Item N failed" log line carry the exception's traceback.
install_langfuse_item_error_logging()

# The item metadata keys the scorers grade against, copied onto the task output because
# Langfuse flattens and truncates ``experiment_item_metadata``.
_EXPECTATION_KEYS = (
    "expected_route",
    "expected_pages",
    "key_facts",
    "forbidden",
    "answerable",
    "required_steps",
    "min_sections",
    "max_retrievals",
)


def _expectations(item) -> dict:
    metadata = getattr(item, "metadata", None) or {}
    return {key: metadata[key] for key in _EXPECTATION_KEYS if key in metadata}


def _local_scores(item_results) -> dict[str, list[float]]:
    """Group each item's evaluator results by score name."""
    scores: dict[str, list[float]] = {}
    for item_result in item_results:
        for evaluation in item_result.evaluations:
            value = evaluation.value
            if isinstance(value, bool):
                value = float(value)
            elif not isinstance(value, (int, float)):
                continue
            scores.setdefault(evaluation.name, []).append(float(value))
    return scores


def _preview(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[:limit]}\N{HORIZONTAL ELLIPSIS}"


def _current_trace_context(client) -> dict[str, str]:
    """Return the active Langfuse experiment task's distributed trace context."""
    trace_id = client.get_current_trace_id()
    parent_span_id = client.get_current_observation_id()
    if not trace_id or not parent_span_id:
        raise RuntimeError("Langfuse experiment task has no active trace context")
    return {"trace_id": trace_id, "parent_span_id": parent_span_id}


def resolve_knowledge_base_id() -> str:
    """Return the evaluation document's Knowledge Base id.

    ``EVAL_KNOWLEDGE_BASE_ID`` wins (CI sets it from ``docpipe eval prepare``); otherwise the
    handbook is published through the real ingestion pipeline and awaited.
    """
    if knowledge_base_id := os.environ.get("EVAL_KNOWLEDGE_BASE_ID"):
        return knowledge_base_id
    from fixture.document import ensure_fixture_document

    return ensure_fixture_document()


class BaseExperiment(ABC):
    """Run one route's dataset against the deployed agent and gate its scores.

    Subclasses declare the dataset, run metadata, and minimum mean per score. The base
    class invokes the Gateway with distributed trace context (each item, including every
    turn of a follow-up item, shares one session), scores the run with the deterministic
    scorers, and raises ``RegressionError`` when a gated mean falls short. No score calls
    a language model.
    """

    dataset_name: str
    experiment_name: str
    experiment_description: str

    # {score_name: minimum mean}. A mean below the minimum raises RegressionError.
    thresholds: dict[str, float]

    # Prefix for the RegressionError message, e.g. "Easy-route experiment below threshold".
    regression_message_prefix: str

    # {dataset_item_id: session_id} recorded as each task starts, so `_run` can name the
    # session behind an item that never made it into `result.item_results`.
    _session_ids: dict[str, str]

    def build_task(self, client, knowledge_base_id: str):
        """Build the task callable for this experiment's dataset items.

        Args:
            client: Langfuse client that owns the active experiment task trace.
            knowledge_base_id: Knowledge Base of the evaluation document.

        Returns:
            An asynchronous task callable accepted by Langfuse experiments.
        """
        started = itertools.count(1)

        async def task(*, item, **kwargs):
            """Invoke and trace one dataset item (one or more turns on one session)."""
            turns = item.input.get("turns") or [item.input["query"]]
            item_num = next(started)
            session_id = f"eval-{item.id}-{uuid.uuid4()}"
            self._session_ids[item.id] = session_id
            logger.info(
                "item %d start [%s] (session_id=%s): %s",
                item_num,
                item.id,
                session_id,
                _preview(turns[-1]),
            )
            try:
                trace_context = _current_trace_context(client)
                run = None
                for prompt in turns:
                    run = await invoke_agent(
                        prompt,
                        knowledge_base_id,
                        session_id=session_id,
                        trace_context=trace_context,
                    )
            except Exception:
                logger.exception(
                    "item %d [%s] failed (session_id=%s)", item_num, item.id, session_id
                )
                raise

            logger.info(
                "item %d done [%s]: route=%s, %d chars, ttft=%s ms, %d retrieval(s)",
                item_num,
                item.id,
                run.route,
                len(run.answer),
                f"{run.ttft_ms:.0f}" if run.ttft_ms is not None else "n/a",
                run.diagnostics.get("retrievals", 0),
            )
            return {
                "answer": run.answer,
                "route": run.route,
                "citations": run.citations,
                "diagnostics": run.diagnostics,
                "ttft_ms": run.ttft_ms,
                "latency_ms": run.latency_ms,
                "session_id": session_id,
                "expectations": _expectations(item),
            }

        return task

    def _failed_items(self, result) -> list[tuple[str, str]]:
        """Return ``(item_id, session_id)`` for each started item missing from the result."""
        completed = set()
        for item_result in result.item_results:
            item = getattr(item_result, "item", None)
            item_id = (
                item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            )
            if item_id is not None:
                completed.add(item_id)
        return [
            (item_id, session_id)
            for item_id, session_id in self._session_ids.items()
            if item_id not in completed
        ]

    def _run(self, run_experiment, client, knowledge_base_id, expected_item_count=None):
        """Run an experiment and enforce its aggregate score thresholds.

        Args:
            run_experiment: Callable that launches the Langfuse experiment run.
            client: Langfuse client that owns the experiment item traces and scores.
            knowledge_base_id: Knowledge Base of the evaluation document.
            expected_item_count: Number of dataset items the run was asked to process, to
                catch items dropped by a task-level exception.
        """
        self._session_ids = {}
        result = run_experiment(
            name=self.experiment_name,
            description=self.experiment_description,
            task=self.build_task(client, knowledge_base_id),
            evaluators=[score_run],
        )
        logger.info(result.format())

        failed = self._failed_items(result)
        for item_id, session_id in failed:
            logger.error(
                "item [%s] never completed (session_id=%s) - see its Langfuse trace",
                item_id,
                session_id,
            )

        item_count = len(result.item_results)
        scores = _local_scores(result.item_results)
        for name, values in sorted(scores.items()):
            if values:
                logger.info(
                    "%s: mean %.3f over %d score(s)",
                    name,
                    sum(values) / len(values),
                    len(values),
                )

        misses = check_regressions(scores, self.thresholds, item_count=item_count)
        messages = [
            f"{name} mean {mean:.3f} < {minimum:.2f}" for name, mean, minimum in misses
        ]
        if failed:
            listed = ", ".join(f"{item_id} (session {sid})" for item_id, sid in failed)
            messages.append(f"{len(failed)} item(s) never completed: {listed}")
        elif expected_item_count is not None and item_count < expected_item_count:
            messages.append(
                f"{expected_item_count - item_count} of {expected_item_count} item(s) never completed"
            )
        if not messages:
            return result

        message = f"{self.regression_message_prefix}: " + "; ".join(messages)
        if failed:
            raise ExperimentItemsFailedError(
                result=result, failed_items=failed, message=message
            )
        raise RegressionError(result=result, message=message)

    def experiment(self, context: RunnerContext):
        """Run the experiment with a prepared Langfuse runner context.

        Args:
            context: Runner context containing the experiment callback and Langfuse client.

        Returns:
            The completed Langfuse experiment result.

        Raises:
            ExperimentItemsFailedError: If any dataset item never completed its task.
            RegressionError: If any gated evaluator mean is below its threshold.
        """
        expected_item_count = len(context.data) if context.data is not None else None
        return self._run(
            context.run_experiment,
            context.client,
            resolve_knowledge_base_id(),
            expected_item_count,
        )

    def main(self) -> None:
        """Run the configured dataset experiment as a command-line entrypoint.

        Raises:
            SystemExit: If the experiment fails a regression threshold.
        """
        langfuse = init_langfuse_client()
        dataset = langfuse.get_dataset(self.dataset_name)
        try:
            self._run(
                dataset.run_experiment,
                langfuse,
                resolve_knowledge_base_id(),
                len(dataset.items),
            )
        except RegressionError as exc:
            raise SystemExit(str(exc)) from exc
