# Evaluations

Langfuse datasets and experiments for the deployed orchestrator. No score uses an LLM as a judge:
every metric is computed from the run itself (route, retrieved pages, citations, text, timings), so
evaluations cost nothing beyond the agent invocations they trigger, and results are reproducible.

## Metrics

| Concern | Score | How it is computed |
|---|---|---|
| Routing | `route_accuracy` | the `route` event equals the item's `expected_route` |
| Retrieval | `retrieval_recall`, `retrieval_mrr` | pages of the retrieved excerpts (runtime diagnostics) vs `expected_pages`; MRR is informational |
| Citations | `citation_presence`, `citation_validity`, `citation_accuracy` | `[[n]]` markers exist; each resolves to a retrieved excerpt; resolved pages are the expected ones. On unanswerable items any citation is a failure |
| Faithfulness | `keyfact_recall`, `no_forbidden_claims` | normalised phrase match (tolerant to `40 °C` / `40 degrees Celsius`) for required facts; forbidden phrases must not appear |
| Abstention | `abstention_correct` | for an unanswerable question the answer says the document does not cover it; for an answerable one it does not refuse |
| Guides | `guide_step_coverage`, `guide_order_validity`, `guide_numbering` | required step keywords are present, appear in order, and the numbered list is consecutive |
| Orchestration | `subagent_use`, `tool_budget` | guide route ran at least `min_sections` subagent sections and no other route delegates; retrievals within the route's budget (easy = exactly one) |
| Responsiveness | `ttft_within_budget` (gated), `ttft_ms`, `latency_ms` (informational) | client-side time to first streamed token vs a per-route budget |
| Shape | `answer_well_formed` | non-empty and below 8,000 characters |

Each route has its own dataset and thresholds (`experiments/run_*_experiment.py`); a mean below its threshold
exits non-zero with a `RegressionError`.

## The evaluation document

Datasets are written against a small synthetic handbook (`fixture/handbook.json`, six pages), rendered to a PDF
at run time by `fixture/pdf_builder.py`, so no PDF is committed. `fixture/document.py` uploads it to
`uploads/eval-handbook.pdf`, so the experiment exercises the real S3, Textract, chunking and Knowledge Base
path, then waits for the registry entry to become `READY`. Set `EVAL_KNOWLEDGE_BASE_ID` to skip that step
(CI does: `docpipe eval prepare` prints the id).

## How a run works

`agent_client.invoke_agent` calls the AgentCore Gateway (the production path) with `"diagnostics": true`, so the
runtime appends a final `diagnostics` event (route, retrieval count, retrieved excerpts, subagent output
counts). The API never sets that flag. The experiment passes its Langfuse trace context via `traceparent`, so
the agent's own spans nest under each experiment item. Multi-turn (`turns`) items reuse one session id and grade
the last turn, which checks follow-up rewriting without a simulated user.

## Layout

| Path | Description |
|---|---|
| `datasets/raw_datasets/{easy,hard,guide}.json` | Items with expectations (`expected_route`, `expected_pages`, `key_facts`, `forbidden`, `answerable`, `required_steps`, `min_sections`, `max_retrievals`) |
| `datasets/base_dataset_creator.py`, `create_*_dataset.py` | Upsert listed items, archive dropped ones |
| `evaluators/scorers.py`, `evaluators/text.py` | The scorers and the text helpers behind them |
| `experiments/` | `BaseExperiment` plus one thin runner per route; `experiment(context)` also works with `langfuse/experiment-action` |
| `fixture/` | Handbook JSON, PDF builder, ingestion publisher |
| `agent_client.py`, `utils/` | Timed Gateway client, SigV4 signing, Langfuse client, threshold gate |

## Run

```bash
make experiment-easy          # or experiment-hard / experiment-guide / experiments
```

The Make targets sync the datasets first, resolve the Gateway and evaluation Knowledge Base, then run the experiment.
By hand, from `apps/agents` (needs `AGENT_GATEWAY_URL`, `EVAL_KNOWLEDGE_BASE_ID` or `DOCUMENTS_BUCKET` + `REGISTRY_TABLE`,
and Langfuse credentials from SSM or the environment):

```bash
uv run --package DocPipelineAgent python evaluations/datasets/create_easy_dataset.py
uv run --package DocPipelineAgent python evaluations/experiments/run_easy_experiment.py
```

Unit tests for the scorers, fixture and client run with the normal suite:
`uv run --package DocPipelineAgent python -m pytest -q`.
