# Ingestion

Turns each PDF uploaded to `s3://<documents-bucket>/uploads/` into its own Bedrock Knowledge Base, using Textract
for extraction and Bedrock's built-in chunking. The frontend does this for you: **Upload PDF**
asks the API for a presigned S3 POST (`POST /v1/documents/upload`, PDF only, size-limited, chunking choice signed in) and the
browser sends the file straight to S3, so it never passes through CloudFront, the load balancer or the API. No PDF lives in this repository.
Chunking and embedding are done by Amazon Bedrock (Knowledge Base `SEMANTIC` chunking + Titan embeddings);
this code only stages Textract's output for it.

```
S3 ObjectCreated  uploads/*.pdf ─► start_extraction ─► Textract (LAYOUT + TABLES, async)
                                                            │ completion (SNS)
                                                            ▼
                                                     process_result
   parse layout blocks -> per-page Markdown + metadata sidecars in s3://<docs>/kb-input/<doc_id>/
   ─► S3 Vectors index + Bedrock Knowledge Base (one per PDF, S3 data source, SEMANTIC chunking)
   ─► StartIngestionJob (Bedrock chunks, embeds, stores)      registry: INDEXING
                                    ▲ EventBridge, every minute
                              check_ingestion ─► registry: READY (or FAILED with the reason)

S3 ObjectRemoved  uploads/*.pdf ─► on_delete ─► deletes the KB, its vector index, staged pages and registry entry
```

| Module | Responsibility |
|---|---|
| `handlers.py` | The four Lambda entrypoints (`start_extraction`, `process_result`, `check_ingestion`, `on_delete`) and document-id derivation |
| `chunking_options.py` | Chooses Bedrock's chunking strategy per upload and validates it |
| `elements.py` | Textract blocks to ordered elements (headers/footers dropped, tables as Markdown) |
| `pages.py` | Elements to one Markdown document per page (headings as `#`, tables as Markdown tables) |
| `knowledge_base.py` | Idempotent S3 Vectors index + KB + S3 data source; stages pages; starts and inspects the ingestion job; deletion |
| `registry.py` | DynamoDB `doc_id` registry (`PROCESSING`, `INDEXING`, then `READY` or `FAILED`) behind `GET /v1/knowledge-bases` |

## Supported PDFs

The pipeline makes no assumptions about a PDF's subject, language or layout:

| PDF | How it is handled |
|---|---|
| Text, multi-column, reports, papers, manuals | Textract layout analysis keeps reading order; headers, footers and page numbers are dropped |
| Scanned / image-only, photographed pages | Textract OCR; a PDF with no readable text ends `FAILED` with a clear reason |
| Tables, spreadsheets exported to PDF | Rendered as Markdown tables |
| Slides, charts, diagrams | Text recognised inside figures is kept |
| Any language or script | Titan Text v2 embeddings are multilingual; non-Latin filenames get a readable id plus a hash |
| Very large PDFs (thousands of pages) | Textract is asynchronous, pages are uploaded concurrently, and Bedrock's ingestion job is observed by a scheduled Lambda, so nothing is bound by a 15-minute Lambda |
| Password-protected or corrupt PDFs | Textract rejects them; the document ends `FAILED` with the error |

### Choosing the chunking

The default suits flowing prose. Pick another Bedrock strategy per upload with S3 object metadata (no code change):

| `chunking` | Best for |
|---|---|
| `semantic` (default) | articles, manuals, reports: split where the meaning shifts |
| `hierarchical` | long structured documents: small child chunks match, larger parent chunks give context |
| `fixed` | uniform text such as logs and transcripts: fixed windows with 10 % overlap |
| `none` | slides, forms, invoices, data tables: one chunk per page |

```bash
make upload-document PDF=deck.pdf CHUNKING=none
uv run scripts/docpipe.py docs upload paper.pdf --chunking hierarchical --max-tokens 400 --wait
# or directly: aws s3 cp deck.pdf s3://<bucket>/uploads/ --metadata chunking=none,max-tokens=300
```

`max-tokens` is clamped to 50-1500; unknown values fall back to `semantic` rather than failing the upload. Deployment-wide
defaults: the `CHUNKING_STRATEGY` and `CHUNK_MAX_TOKENS` Lambda environment variables. Bedrock cannot change a data
source's chunking after creation, so re-uploading with a different choice recreates the data source (its old vectors
are deleted with it).

Design notes:

- Bedrock chunks and embeds. The data source uses the built-in semantic chunking strategy
  (`maxTokens=300`, `bufferSize=1`, `breakpointPercentileThreshold=95`, see `SEMANTIC_CHUNKING`); the Knowledge Base
  embeds with Titan Text v2 (1024-d, cosine). Nothing here computes an embedding or splits text.
- One Markdown file per page keeps every chunk attributable to an exact page, which is what the agent cites. A
  `.metadata.json` sidecar carries `doc_id`, `source`, `page` and `section`, which Bedrock stores with each chunk.
  Chunks therefore never span a page boundary.
- Any failure (Textract, an empty document, an ingestion job that indexed nothing) ends in
  `FAILED` with the reason in the registry, which `make list-documents` and the API surface.
- Ingestion is idempotent. The document id is `<filename-slug>-<sha1(key)[:6]>`. Re-uploading a PDF reuses its
  Knowledge Base, replaces the staged pages and re-syncs; the ingestion job removes vectors of pages that disappeared.
- Quota: each PDF creates a Knowledge Base; Bedrock's default is 100 per account and region.
- No dependencies are bundled: `boto3` comes from the Lambda runtime.

```bash
cd apps/ingestion && uv run --package DocPipelineIngestion python -m pytest -q
```
