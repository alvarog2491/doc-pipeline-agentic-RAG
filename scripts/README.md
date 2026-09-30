# scripts/

Everything `make` does, plus the helpers CI runs directly. The [Makefile](../Makefile) only declares
configuration (`ENV`, `AWS_REGION`, `AWS_PROFILE`) and delegates one target to one subcommand of
[`docpipe.py`](docpipe.py).

```
docpipe.py            the entry point: `uv run scripts/docpipe.py <group> <command>`
                      PEP 723 inline metadata declares boto3 + httpx, so `uv run`
                      resolves it in an ephemeral environment and never touches the
                      uv workspace the apps share

pipeline_tools/       cli.py         argparse wiring, the list of every command
                      config.py      every environment-derived name (ECR repositories, state
                                     key, SSM parameter, prompt label)
                      context.py     what a command is handed: config + AWS session,
                                     .env loading, refuse_managed
                      aws.py         the boto3 session, ECR registry, SSM
                      terraform.py   init / apply / destroy / outputs against per-env state
                      shell.py       REPO_ROOT, require(), subprocess, uv_script()
                      env_file.py    reading and rewriting .env
                      github.py      $GITHUB_OUTPUT / $GITHUB_STEP_SUMMARY
                      ui.py          stage banners, stderr logging, Failure

pipeline_tools/commands/
                      deploy.py      deploy dev / destroy / outputs / verify
                      agent.py       smoke-test (one signed Gateway call against a READY document)
                      docs.py        upload / list documents
                      prompts.py     prompts sync
                      experiments.py prepare / sync-datasets / easy / hard / guide / all
                      local.py       compose-up / run-agent / frontend-dev

prompts/              sync_prompts.py   upserts apps/agents/prompts/*.yaml by label
ci/                   tf.sh             terraform against one env's remote state (CI only)
```

## The command surface

Run `uv run scripts/docpipe.py --help`, or `... <group> --help`, for the current list.

| Command | Makefile target | Also called by |
|---|---|---|
| `deploy dev` | `make dev-deploy` | |
| `deploy destroy` | `make dev-destroy` | |
| `deploy outputs` | | `cd-staging.yml` |
| `deploy verify` | `make dev-verify` | `cd-staging.yml`, `cd-production.yml` |
| `agent smoke-test` | | `deploy verify` |
| `docs upload <pdf> [--wait] [--chunking …] [--max-tokens N]` | `make upload-document PDF=... [CHUNKING=...]` | |
| `docs list` | `make list-documents` | |
| `prompts sync` | `make sync-prompts` | `deploy dev`, `cd-staging.yml`, `cd-production.yml` |
| `experiments prepare` | | |
| `experiments sync-datasets` | `make sync-datasets` | |
| `experiments easy` / `hard` / `guide` / `all` | `make experiment-easy` ... `make experiments` | (the experiment scripts also run under `cd-staging.yml` via `langfuse/experiment-action`) |
| `local compose-up` | `make compose-up` (`GATEWAY=local\|deployed`) | |
| `local run-agent` | `make run-agent` | |
| `local frontend-dev` | `make run-frontend-dev` | |

Staging and production infrastructure is applied by the workflows through `ci/tf.sh`, never by `docpipe`.

## Conventions

- **Two kinds of Python here, and the split is dependencies.** `pipeline_tools/` is one package behind one entry
  point, resolved once from `docpipe.py`'s inline metadata. `prompts/sync_prompts.py` stays separate because it needs
  langfuse, and a deploy has no business installing it - it declares its own PEP 723 block and the CLI runs it as a
  subprocess.
- **Nothing spells a resource name out by hand.** `config.py` derives every repository, state key and label from
  `ENV`; everything else comes from Terraform outputs.
- **Configuration arrives as environment variables** (`ENV`, `AWS_REGION`, `AWS_PROFILE`, `GATEWAY`,
  `TF_STATE_BUCKET`, ...), which the Makefile exports and the workflows set in an `env:` block. Command-line arguments
  are for genuine inputs - a PDF path.
- **Logging goes to stderr** (`info`, `Stages`, `Failure`), so a command can return a value on stdout for its caller to
  capture. `deploy outputs` is appended straight to `$GITHUB_OUTPUT`.
- **Failures are `Failure`, not tracebacks.** `raise die("...")` prints `ERROR: <message>` and exits 1.
- **Subprocesses take a list argv**, never a shell string, so a value carrying a space or a `$` is an argument rather
  than a parse.
- **Credentials are read, never written.** The Langfuse keys are bootstrapped once per environment by hand (README
  "First-time bootstrap"), so nothing here - and no `terraform destroy` - can create, rotate or delete them.
- **Prod and staging are CI/CD only.** Anything that mutates infrastructure by hand calls `Context.refuse_managed`.
  Staging is deployed by `.github/workflows/cd-staging.yml` on a pull request, production by
  `.github/workflows/cd-production.yml` on a push to main.
