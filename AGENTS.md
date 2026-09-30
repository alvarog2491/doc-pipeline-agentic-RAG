# Doc Pipeline Agentic RAG Project

## Product Scope

A conversational application over documents the user uploads:

1. Uploading a PDF to S3 triggers an ingestion pipeline (Lambda → Amazon Textract → per-page Markdown → one
   Bedrock Knowledge Base per PDF on S3 Vectors). Chunking and embedding are Bedrock's own (`SEMANTIC` chunking +
   Titan embeddings); do not reimplement them in Lambda code.
2. A React frontend lets the user pick one of those documents and chat with it.
3. A Python FastAPI REST API validates the request and streams the answer as Server-Sent Events
   by invoking the agent through Amazon Bedrock AgentCore Gateway.
4. The agent (a LangGraph orchestrator) routes each question to an easy, hard or step-by-step-guide
   workflow, and owns Langfuse tracing, monitoring, and experiment/evaluation instrumentation.

There is intentionally no login, authentication, authorization, or user-account system. Do not introduce one
unless a future user request explicitly changes this scope. Session IDs provide conversational continuity only;
they are not an authentication or authorization boundary. No PDF is committed to this repository.

Keep the architecture direct and easy to operate. Prefer small, explicit implementations over speculative
abstractions.

## Repository Layout

```text
apps/
├── agents/            # Python LangGraph orchestrator deployed to AgentCore Runtime; Langfuse + evaluations live here
├── api/               # Python/FastAPI REST + SSE API that invokes AgentCore through the Gateway
├── frontend/          # React/Vite chat frontend with a document (Knowledge Base) dropdown
├── ingestion/         # S3-triggered Lambdas: Textract extraction, page staging, per-PDF Knowledge Base
└── online-evaluators/ # AgentCore code-based (Lambda) evaluators used by the production release gate
terraform/             # Root module + modules (ecr, data, agentcore, evaluations, alb, ecs, cloudfront), bootstrap/, tests/
scripts/               # Everything `make` does, plus the helpers CI runs directly - see scripts/README.md
packages/
├── config-ts/         # Shared TypeScript compiler configuration
└── shared-types/      # Browser-side SSE event types and runtime validation
```

## Environments

`dev`, `staging` and `prod` (plus ephemeral `pr-*`), defined in `terraform/config.tf`. `staging` is spread from
`prod` there so the two cannot drift, and lives in its own AWS account. Each environment keeps its own Terraform
state object (`<env>/terraform.tfstate`) in the bucket created by `terraform/bootstrap`.

**Only `dev` may be deployed by hand.** `staging` and `prod` are deployed exclusively by
`.github/workflows/cd-staging.yml` (on a pull request into main) and `cd-production.yml` (on the push to main that
follows the merge). Every hand-run command that mutates infrastructure calls `Context.refuse_managed`
(`scripts/pipeline_tools/context.py`), which refuses both - do not add a make target or a manual deploy path for
either, and do not weaken that guard to work around it.

Production never applies a new agent version directly. `cd-production.yml` builds the image and runs
[`alvarog2491/agentcore-ab-release-gate`](https://github.com/alvarog2491/agentcore-ab-release-gate), which A/B tests
it against `control` on live Gateway traffic, scores both with the online evaluators in
`apps/online-evaluators` (deterministic Lambda checks, no LLM judge) and promotes only when every quality gate
passes. In that environment Terraform ignores the runtime image and the `control` endpoint version. Langfuse remains
independent production tracing and offline experiment infrastructure.

## Architectural Invariants

1. The frontend communicates with the agent only through the API.
2. The API sends SigV4-signed requests to the AgentCore Gateway's control target, which routes to the AgentCore
   Runtime `control` endpoint (the release gate adds a candidate target only during an A/B test).
3. Langfuse monitoring and experiment code belongs in the AgentCore agent, not the API.
4. External requests are untrusted and must be validated before invoking the agent: the prompt, the session UUID
   and the Knowledge Base id (which must be a `READY` document in the registry).
5. Do not expose exception details to API clients or log prompt contents in the API.
6. Keep application and infrastructure configuration aligned: runtime ARN, gateway URL, table and bucket names,
   ports and IAM grants are wired through Terraform outputs and module inputs, never copied manually.
7. Uploaded documents are private. The API presigns short-lived links to cited pages; nothing is public-read.
8. Answers cite retrieved excerpts as `[[n]]`; the runtime resolves markers to `{page, source, section}` and drops
   markers that name no retrieved excerpt.

## API Contract (REST + SSE, `/v1`)

- `POST /v1/chat/stream` body `{sessionId (UUID), knowledgeBaseId, prompt}`; response is `text/event-stream`.
  Event types (`event:` field and `type` in the JSON): `route`, `progress`, `delta`, `citations`, `completed`,
  `error`. Every event carries `requestId` and a monotonic `sequence` starting at 0. Events are flushed as the agent
  emits them; nothing is buffered until the answer is complete.
- `POST /v1/documents/upload` body `{filename, sizeBytes, chunking?, maxTokens?}` returns a presigned S3 POST
  (`{url, fields, key, maxBytes}`). The browser uploads the PDF straight to S3, which triggers ingestion; the policy pins
  the key, content type, size range and chunking metadata. There is no login, so this endpoint is open by design:
  keep the size limit and PDF-only checks, and never make it write outside `uploads/`.
- `GET /v1/knowledge-bases` lists documents (`PROCESSING`/`INDEXING`/`READY`/`FAILED`); only `READY` ones can be chatted with.
- `POST /v1/feedback` `{sessionId, outcome: helpful|not_helpful, comment?}`; `GET /health` for the load balancer.
- Make v1 changes additive. Removing or renaming fields, changing required fields, or changing their meaning
  requires `/v2`. Update Python protocol models (`apps/api/chat_api/core/protocol.py`), TypeScript types and runtime
  validation (`packages/shared-types/src/events.ts`), documentation, and contract tests together.

## AgentCore Invocation

- Runtime input is `{ "prompt": "...", "knowledgeBaseId": "..." }`; the prompt must be a non-empty string and the id a
  well-formed Bedrock Knowledge Base id. `"diagnostics": true` is reserved for the evaluation suite.
- Forward the session UUID in `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` for conversation continuity.
- The task role of the API needs only `bedrock-agentcore:InvokeGateway` for the configured Gateway, `dynamodb:Scan`
  on the registry, and `s3:GetObject` / `s3:PutObject` on `uploads/*` (to presign citation links and browser uploads).
- The agent uses LangGraph conversation state and Langfuse callbacks. Keep monitoring credentials in the agent
  runtime environment.

## Development Commands

```bash
# TypeScript workspace
pnpm -r test
pnpm -r build

# uv workspace: one ./.venv and one ./uv.lock for every app under apps/.
# Never create a per-app venv. Members are virtual (package = false), so this installs
# their dependencies only - run each app from its own directory.
uv sync --all-packages

# API
cd apps/api
uv run --package doc-pipeline-api python -m pytest -q
uv run --package doc-pipeline-api uvicorn chat_api.main:app --reload --port 8000

# Agent
cd apps/agents
uv run --package DocPipelineAgent python -m pytest -q
uv run --package DocPipelineAgent python main.py

# Ingestion and online evaluators
(cd apps/ingestion && uv run --package DocPipelineIngestion python -m pytest -q)
(cd apps/online-evaluators && uv run --package DocPipelineOnlineEvaluators python -m pytest -q)

# Infrastructure (no AWS credentials needed)
make tf-test        # fmt -check, validate, and the plan-level tests with mocked providers
```

## Python Coding and Documentation

- Preserve runtime behavior, imports, type annotations, and public signatures during documentation-only work.
- Use concise module docstrings that describe the module's responsibility rather than its implementation history.
- Write all Python docstrings under `apps/` in
  [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings). Use a summary line
  ending in a period and add `Args:`, `Returns:`, `Yields:`, and `Raises:` sections when they apply. Describe
  semantics and constraints; do not repeat signature types.
- Treat functions exposed to an LLM, agent nodes, runtime entrypoints, and externally supplied callbacks as
  prompt-grade public interfaces. Give them an imperative summary, explain when and why the runtime should use them,
  document every parameter, describe the returned schema, and list non-trivial exceptions.
- Give public classes, methods, and functions concise Google-style documentation without LLM-specific invocation
  guidance. Document constructor fields in the class docstring instead of duplicating them on `__init__`.
- Give simple private helpers a single-line docstring or omit it when the name and annotations are self-explanatory.
  Reserve multi-line private docstrings for non-obvious contracts, external side effects, or exceptional behavior.
- Do not add docstrings to tests merely to satisfy documentation lint rules. Prefer descriptive test names; document
  only fixtures or helpers whose contract is not obvious.
- Keep comments that explain intent, safety constraints, external-service behavior, or a non-obvious algorithm.
  Remove comments that only narrate the following statement or preserve obsolete implementation details.
- For Python changes, run focused tests plus `ruff check` and `ruff format --check` on the affected scope. Run the
  complete application test suite when executable behavior changes.

## Change Standards

- Define or update behavioral tests before changing protocol or invocation behavior.
- Follow the Python coding and documentation rules above for every file under `apps/`.
- Keep message types as discriminated unions and validate at runtime on both sides of the API boundary.
- Evaluations must stay deterministic and cheap: do not add LLM-as-a-judge scorers.
- Prefer existing dependencies and standard-library features over new packages.
- Run the focused tests while implementing, then the complete Python tests, TypeScript tests, TypeScript build and
  `make tf-test`.
- Preserve unrelated user changes in a dirty worktree.
- Never edit generated build output in `dist/` or `.terraform/`.
