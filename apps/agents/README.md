# Agent

Python **LangGraph orchestrator** deployed to Amazon Bedrock AgentCore Runtime. The user picks one
uploaded document (one Bedrock Knowledge Base per PDF); every turn is routed by an LLM judge to
one of three workflows.

```mermaid
flowchart TD
    S([start]) --> C[classify<br/>route + standalone question]
    C -->|easy| E[easy_answer<br/>1 retrieval, streamed answer]
    C -->|hard| D[decompose] --> R[retrieve_many<br/>parallel searches] --> A[analyze<br/>sufficiency check]
    A -->|gaps, first time| R
    A -->|sufficient| Y[synthesize<br/>streamed answer]
    C -->|guide| P[guide_plan<br/>outline]
    P --> X1[section_extractor subagent]:::sub
    P --> X2[section_extractor subagent]:::sub
    P --> X3[prerequisites_checker subagent]:::sub
    X1 --> G[guide_assemble<br/>streamed guide]
    X2 --> G
    X3 --> G
    E --> F([end])
    Y --> F
    G --> F
    classDef sub fill:#eef,stroke:#88a
```

| Route | When | What runs |
|---|---|---|
| `easy` | a fact, definition, or small talk | one retrieval (5 passages) → one streamed, cited answer. First token arrives after the router call and one search. |
| `hard` | needs comparing, combining or reasoning | sub-question decomposition → parallel retrieval → `analyze` cross-check (one gap-filling round at most) → streamed synthesis. |
| `guide` | a complete step-by-step procedure | overview retrieval → outline → **subagents** (`section_extractor` per section, `prerequisites_checker`) run in parallel via `Send` and sweep the document exhaustively → streamed, ordered, cited guide. |

Only the final answer is streamed. Everything the client sees (`route`, `progress`, `chunk`, and the final
`citations`) goes through `events.emit`, so internal model calls never leak into the response. Answers cite
excerpts as `[[n]]`; `citations.py` resolves those markers to `{page, source, section}` after the run.

## Runtime contract

Request: `{"prompt": "...", "knowledgeBaseId": "<10-char id>"}`, or `{"type": "feedback", "outcome": "helpful|not_helpful", "comment": "..."}`.
The AgentCore session id keeps the conversation (`thread_id = <session>:<knowledgeBaseId>`); it is not an auth boundary.

Response events, in order: `{"route": ...}`, `{"progress": ...}`*, `{"chunk": ...}`*, `{"citations": [...]}`.

## Layout

| Path | Description |
|---|---|
| `main.py` | AgentCore entrypoint: validates the payload, streams graph events, records Langfuse metadata (`route`, retrieved excerpts, citations) and feedback scores. |
| `graph.py` | `build_agent` — wires the nodes above into a `StateGraph` with an in-memory checkpointer. |
| `router.py`, `easy.py`, `hard.py`, `guide.py` | The nodes of each workflow. |
| `state.py` | Graph state and the Pydantic schemas for structured model outputs. |
| `nodes_common.py`, `llm.py`, `events.py` | Shared dependencies, model-call helpers, and the custom event stream. |
| `excerpts.py`, `citations.py`, `retrieval.py` | Numbered excerpts, marker resolution, and Bedrock `Retrieve` on the selected Knowledge Base. |
| `prompts/` | Git-versioned Langfuse chat prompts (see `prompts/README.md`). |
| `prompting.py`, `langfuse_client.py`, `observability.py` | Prompt loading, Langfuse client, W3C trace-context propagation. |
| `model/` | Bedrock Converse model factory (`BEDROCK_MODEL_ID`; optional smaller `BEDROCK_ROUTER_MODEL_ID` for `classify`). |
| `evaluations/` | Langfuse datasets, deterministic scorers and experiments. |

## Run

```bash
uv run --package DocPipelineAgent python -m pytest -q     # from apps/agents
uv run --package DocPipelineAgent python main.py          # ASGI server on 0.0.0.0:8080
```

## Docstrings

Python code here uses [Google-style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings):
a one-line summary followed, where they apply, by `Args:`, `Returns:`, `Yields:` and `Raises:` sections.
