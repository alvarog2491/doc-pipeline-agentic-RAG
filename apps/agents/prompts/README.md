# Prompts

Git-versioned source of truth for the agent's Langfuse chat prompts. Edit the YAML files here, not in the
Langfuse UI: UI edits get overwritten on the next sync (`make sync-prompts`).

| File | Node | Variables |
|---|---|---|
| `router.yaml` | `classify`: easy / hard / guide + standalone question | none |
| `answer.yaml` | `easy_answer`: one retrieval, streamed cited answer | `question`, `context` |
| `decompose.yaml` | `decompose` (hard): sub-queries | `question` |
| `analyze.yaml` | `analyze` (hard): sufficiency check and notes | `question`, `context` |
| `synthesize.yaml` | `synthesize` (hard): final streamed answer | `question`, `context`, `notes` |
| `guide_plan.yaml` | `guide_plan`: outline of the procedure | `question`, `context` |
| `guide_section.yaml` | `section_extractor` subagent | `question`, `heading`, `context` |
| `guide_prerequisites.yaml` | `prerequisites_checker` subagent | `question`, `context` |
| `guide_assemble.yaml` | `guide_assemble`: final streamed guide | `question`, `title`, `draft` |

Every file is `type: chat` with a system message, `{{variable}}` placeholders, and a trailing
`messages` placeholder for chat history. Do not put literal braces in prompt text. Excerpts are cited
as `[[n]]`; the runtime resolves those markers to page metadata (`citations.py`).
