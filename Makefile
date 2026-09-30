# Entry point for local development and personal dev deploys.
#
# Every target is one subcommand of scripts/docpipe.py (see scripts/README.md) - this file
# only declares configuration and delegates, so the logic stays testable and readable in
# Python rather than in escaped, backslash-continued recipes.
#
# Staging and production are deployed exclusively by .github/workflows/.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Override on the command line: `make dev-deploy AWS_PROFILE=my-profile ENV=dev`.
# Exported so the CLI reads them from the environment.
export ENV         ?= dev
export AWS_REGION  ?= eu-central-1
export AWS_PROFILE ?= default

# Optional, consumed by `compose-up`: local (default) talks to the local agents
# container, deployed resolves and injects the real AgentCore Gateway URL.
export GATEWAY

# One entry point for everything. `uv run` resolves the CLI's dependencies from the inline
# metadata at the top of scripts/docpipe.py, so there is nothing to install first and no
# dependency on the uv workspace this repository's apps share.
DOCPIPE := uv run scripts/docpipe.py

.PHONY: help compose-up run-agent run-frontend-dev dev-deploy dev-destroy dev-verify \
        upload-document list-documents sync-prompts \
        sync-datasets experiment-easy experiment-hard experiment-guide experiments \
        tf-bootstrap tf-test

help: ## Show this help
	@echo "Targets (ENV=$(ENV) AWS_REGION=$(AWS_REGION) AWS_PROFILE=$(AWS_PROFILE)):"
	@grep -hE '^[a-z][a-z-]*:.*## ' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN { FS = ":.*## " } { printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2 }'

## --- Local development ------------------------------------------------------

compose-up: ## Build and run the full local container set with file watching (GATEWAY=local|deployed)
	@$(DOCPIPE) local compose-up

run-agent: ## Run apps/agents from source, no Docker, against the deployed dev environment
	@$(DOCPIPE) local run-agent

run-frontend-dev: ## Run the local frontend against the deployed dev API
	@$(DOCPIPE) local frontend-dev

## --- Documents ---------------------------------------------------------------

upload-document: ## Upload a PDF (PDF=path/to/file.pdf, optional CHUNKING=semantic|hierarchical|fixed|none) and wait until READY
	@test -n "$(PDF)" || { echo "usage: make upload-document PDF=path/to/file.pdf" >&2; exit 2; }
	@$(DOCPIPE) docs upload "$(PDF)" --wait $(if $(CHUNKING),--chunking $(CHUNKING))

list-documents: ## List ingested documents with their status and Knowledge Base id
	@$(DOCPIPE) docs list

## --- Experiments (deterministic scores, no LLM judge) -----------------------------

sync-datasets: ## Make every Langfuse evaluation dataset match evaluations/datasets/raw_datasets/*.json
	@$(DOCPIPE) experiments sync-datasets

experiment-easy: ## Run the easy-route dataset against the deployed agent (AGENT_GATEWAY_URL= for a local one)
	@$(DOCPIPE) experiments easy

experiment-hard: ## Run the hard-route dataset against the deployed agent
	@$(DOCPIPE) experiments hard

experiment-guide: ## Run the guide-route dataset against the deployed agent
	@$(DOCPIPE) experiments guide

experiments: ## Run every evaluation dataset, in the order cd-staging.yml runs them
	@$(DOCPIPE) experiments all

## --- Deploy -------------------------------------------------------------------

dev-deploy: ## Deploy everything to dev: both images and every Terraform module
	@$(DOCPIPE) deploy dev

dev-verify: ## Check the deployed dev environment serves traffic end to end
	@$(DOCPIPE) deploy verify

dev-destroy: ## Destroy every resource in this environment (confirmation required)
	@$(DOCPIPE) deploy destroy

tf-bootstrap: ## One-time per account: create the S3 bucket that holds Terraform state
	cd terraform/bootstrap && terraform init && terraform apply

tf-test: ## Validate the Terraform configuration and run its plan-level tests (no AWS needed)
	cd terraform && terraform init -backend=false -input=false >/dev/null && terraform fmt -check -recursive && terraform validate && terraform test

## --- Prompts ---------------------------------------------------------------------

sync-prompts: ## Push apps/agents/prompts/*.yaml to Langfuse
	@$(DOCPIPE) prompts sync
