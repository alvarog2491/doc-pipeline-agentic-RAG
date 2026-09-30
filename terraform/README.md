# terraform/

One root module, one state object per environment.

```
versions.tf, variables.tf, config.tf   providers, inputs, the per-environment configuration
main.tf, outputs.tf                    module wiring and the outputs the CLI, CI and release gate read
defaults.json                          model / Langfuse defaults shared with scripts/ (local dev)
modules/
  ecr/          agent + api repositories (KMS, scan on push, keep 10 images)
  data/         documents bucket (private; CORS lets the frontend upload with a presigned POST), S3 Vectors bucket, DynamoDB registry, Textract SNS topic + role,
                Knowledge Base service role (reads the staged pages, embeds, stores vectors), the three ingestion
                Lambdas, the S3 trigger and the one-minute `check_ingestion` schedule
  agentcore/    runtime execution role, runtime, `control` endpoint, gateway + control target
  evaluations/  code-based evaluator Lambda, four evaluators, the online-evaluation template and
                the A/B-test role - release-gate environments only
  alb/          default-VPC load balancer (idle timeout 300 s for SSE)
  ecs/          Fargate service for the API, its task role (Gateway + registry + presign only)
  cloudfront/   HTTPS front for the ALB; caching and compression off so SSE flushes per event
bootstrap/      one-time S3 bucket for Terraform state
tests/          plan-level tests with mocked providers (`terraform test`)
envs/           <env>.tfvars and how remote state is selected
```

## Environments

Defined in [`config.tf`](config.tf): `dev` (disposable, API scaled to zero), `prod` (retains state, immutable image
tags, **release-gated**), `staging` (spread from `prod`, disposable, applied directly) and `pr-<n>` (inherits `dev`).

In a release-gated environment the AgentCore runtime image and the `control` endpoint version are `ignore_changes`:
[`agentcore-ab-release-gate`](https://github.com/alvarog2491/agentcore-ab-release-gate) owns promotion after the first
apply. Two resource variants exist because Terraform's `lifecycle` block cannot be conditional.

## Usage

```bash
make tf-test                       # fmt, validate and the plan-level tests; no AWS credentials
make tf-bootstrap                  # once per account
make dev-deploy                    # builds images and applies dev (wraps init + apply)
```

Staging and production are applied only by the workflows (`scripts/ci/tf.sh`). Known assumptions to confirm on the first
real apply: S3 Vectors and the AgentCore evaluator resources are available in the chosen region, and the release gate
accepts the Terraform-created gateway (the provider only offers the default MCP protocol type, which supports the HTTP
runtime target used here).
