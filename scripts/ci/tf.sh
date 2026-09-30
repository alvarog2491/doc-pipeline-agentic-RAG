#!/usr/bin/env bash
# Run terraform against one environment's remote state, the way `docpipe` does locally.
#
#   scripts/ci/tf.sh <env> <terraform args...>
#   scripts/ci/tf.sh prod apply -auto-approve -var-file=envs/prod.tfvars -var agent_image_tag=sha-1
#
# The state bucket name contains the AWS account id, so it is resolved here from the
# credentials the job already assumed (or taken from TF_STATE_BUCKET). Only CI calls this:
# staging and production are never deployed by hand.
set -euo pipefail

env_name="${1:?usage: tf.sh <env> <terraform args...>}"
shift

account="$(aws sts get-caller-identity --query Account --output text)"
bucket="${TF_STATE_BUCKET:-doc-pipeline-tfstate-${account}}"

cd "$(dirname "$0")/../../terraform"
terraform init -reconfigure -input=false \
  -backend-config="bucket=${bucket}" \
  -backend-config="key=${env_name}/terraform.tfstate" \
  -backend-config="region=${AWS_REGION:?AWS_REGION must be set}" \
  -backend-config="use_lockfile=true" >/dev/null

exec terraform "$@"
