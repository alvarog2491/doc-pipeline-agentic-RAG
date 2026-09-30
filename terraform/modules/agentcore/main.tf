variable "env" {
  type = string
}

variable "suffix" {
  type = string
}

variable "agent_repository_url" {
  type = string
}

variable "agent_repository_arn" {
  type = string
}

variable "image_tag" {
  type = string
}

variable "bedrock_model_id" {
  type = string
}

variable "bedrock_router_model" {
  description = "Optional smaller model for the routing step; empty reuses the main model."
  type        = string
  default     = ""
}

variable "bedrock_temperature" {
  type = number
}

variable "langfuse_base_url" {
  type = string
}

variable "release_gate_managed" {
  description = "When true the release gate promotes agent versions, so Terraform ignores the runtime image and the control endpoint version after creation."
  type        = bool
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  region       = data.aws_region.current.region
  runtime_name = "DocPipelineAgent_${replace(var.env, "-", "_")}"

  langfuse_parameter_name = "/doc-pipeline-agent/${var.env}/langfuse"
  langfuse_parameter_arn  = "arn:aws:ssm:${local.region}:${local.account_id}:parameter${local.langfuse_parameter_name}"

  # Gateway targets and Runtime enforce separate request-header allowlists:
  # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-headers.html
  # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-header-allowlist.html
  trace_headers = ["traceparent"]

  environment_variables = merge(
    {
      AWS_REGION                         = local.region
      AWS_DEFAULT_REGION                 = local.region
      BEDROCK_MODEL_ID                   = var.bedrock_model_id
      BEDROCK_TEMPERATURE                = tostring(var.bedrock_temperature)
      PROMPT_LABEL                       = var.env
      LANGFUSE_TRACING_ENVIRONMENT       = var.env
      LANGFUSE_SSM_PARAMETER_NAME        = local.langfuse_parameter_name
      LANGFUSE_BASE_URL                  = var.langfuse_base_url
      AGENT_OBSERVABILITY_ENABLED        = "true"
      UNIFIED_TRACES_DESTINATION_ENABLED = "true"
    },
    var.bedrock_router_model != "" ? { BEDROCK_ROUTER_MODEL_ID = var.bedrock_router_model } : {},
  )
}

# ---------------------------------------------------------------- runtime execution role
data "aws_iam_policy_document" "runtime_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:*"]
    }
  }
}

data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "PullAgentImage"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [var.agent_repository_arn]
  }
  statement {
    sid       = "EcrAuthorization"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "RuntimeLogs"
    actions   = ["logs:CreateLogGroup", "logs:DescribeLogStreams", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }
  statement {
    sid       = "DescribeLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:*"]
  }
  statement {
    # AgentCore unified observability creates the account-level delivery policy.
    sid       = "ObservabilityDelivery"
    actions   = ["logs:PutResourcePolicy"]
    resources = ["*"]
  }
  statement {
    sid       = "Tracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }
  statement {
    sid = "WorkloadIdentity"
    actions = [
      "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
      "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:workload-identity-directory/default",
      "arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:workload-identity-directory/default/workload-identity/*",
    ]
  }
  statement {
    sid     = "InvokeModels"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:*:${local.account_id}:inference-profile/*",
      "arn:aws:bedrock:*:${local.account_id}:application-inference-profile/*",
    ]
  }
  statement {
    # Every uploaded PDF gets its own Knowledge Base, created at runtime by the ingestion
    # Lambda, so the grant covers the account's Knowledge Bases rather than fixed ARNs.
    sid       = "SearchKnowledgeBases"
    actions   = ["bedrock:Retrieve"]
    resources = ["arn:aws:bedrock:${local.region}:${local.account_id}:knowledge-base/*"]
  }
  statement {
    sid       = "ReadLangfuseCredentials"
    actions   = ["ssm:GetParameter"]
    resources = [local.langfuse_parameter_arn]
  }
}

resource "aws_iam_role" "runtime" {
  name_prefix        = "doc-pipeline-${var.env}-runtime-"
  assume_role_policy = data.aws_iam_policy_document.runtime_trust.json
}

resource "aws_iam_role_policy" "runtime" {
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime.json
}

# ---------------------------------------------------------------- runtime + control endpoint
# Two variants because `lifecycle` cannot be conditional: in a release-gate environment the
# gate (alvarog2491/agentcore-ab-release-gate) owns the image and the control endpoint's
# version after the first apply, so Terraform must not fight it.
resource "aws_bedrockagentcore_agent_runtime" "managed" {
  count = var.release_gate_managed ? 0 : 1

  agent_runtime_name    = local.runtime_name
  description           = "Doc Pipeline conversational AI agent"
  role_arn              = aws_iam_role.runtime.arn
  environment_variables = local.environment_variables

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${var.agent_repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  request_header_configuration {
    request_header_allowlist = local.trace_headers
  }

  depends_on = [aws_iam_role_policy.runtime]
}

resource "aws_bedrockagentcore_agent_runtime" "gated" {
  count = var.release_gate_managed ? 1 : 0

  agent_runtime_name    = local.runtime_name
  description           = "Doc Pipeline conversational AI agent"
  role_arn              = aws_iam_role.runtime.arn
  environment_variables = local.environment_variables

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${var.agent_repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  request_header_configuration {
    request_header_allowlist = local.trace_headers
  }

  depends_on = [aws_iam_role_policy.runtime]

  lifecycle {
    ignore_changes = [agent_runtime_artifact]
  }
}

locals {
  runtime = var.release_gate_managed ? aws_bedrockagentcore_agent_runtime.gated[0] : aws_bedrockagentcore_agent_runtime.managed[0]
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "managed" {
  count = var.release_gate_managed ? 0 : 1

  name                  = "control"
  description           = "Endpoint for production traffic"
  agent_runtime_id      = local.runtime.agent_runtime_id
  agent_runtime_version = local.runtime.agent_runtime_version
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "gated" {
  count = var.release_gate_managed ? 1 : 0

  name             = "control"
  description      = "Stable endpoint for production traffic; the release gate promotes versions onto it"
  agent_runtime_id = local.runtime.agent_runtime_id

  lifecycle {
    ignore_changes = [agent_runtime_version]
  }
}

locals {
  control_endpoint_name = var.release_gate_managed ? aws_bedrockagentcore_agent_runtime_endpoint.gated[0].name : aws_bedrockagentcore_agent_runtime_endpoint.managed[0].name
}

# ---------------------------------------------------------------- gateway
data "aws_iam_policy_document" "gateway_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "gateway" {
  statement {
    sid     = "InvokeRuntimeVersions"
    actions = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [
      local.runtime.agent_runtime_arn,
      "${local.runtime.agent_runtime_arn}/runtime-endpoint/*",
    ]
  }
}

resource "aws_iam_role" "gateway" {
  name_prefix        = "doc-pipeline-${var.env}-gateway-"
  assume_role_policy = data.aws_iam_policy_document.gateway_trust.json
  description        = "Allows the AgentCore Gateway to invoke Doc Pipeline runtime versions"
}

resource "aws_iam_role_policy" "gateway" {
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.gateway.json
}

# A dedicated gateway. The release gate adds a candidate target and a weighted routing
# rule to it for the duration of an A/B test, then removes them.
resource "aws_bedrockagentcore_gateway" "this" {
  name            = "DocPipelineGateway${var.suffix}"
  description     = "Routes sticky sessions between the control and candidate agent versions"
  authorizer_type = "AWS_IAM"
  role_arn        = aws_iam_role.gateway.arn

  depends_on = [aws_iam_role_policy.gateway]
}

resource "aws_bedrockagentcore_gateway_target" "control" {
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  name               = "DocPipelineControl"
  description        = "Default production target"

  target_configuration {
    http {
      agentcore_runtime {
        arn       = local.runtime.agent_runtime_arn
        qualifier = local.control_endpoint_name
      }
    }
  }

  credential_provider_configuration {
    gateway_iam_role {}
  }

  metadata_configuration {
    allowed_request_headers = local.trace_headers
  }
}

output "runtime_id" {
  value = local.runtime.agent_runtime_id
}

output "runtime_arn" {
  value = local.runtime.agent_runtime_arn
}

output "runtime_name" {
  value = local.runtime_name
}

output "gateway_id" {
  value = aws_bedrockagentcore_gateway.this.gateway_id
}

output "gateway_arn" {
  value = aws_bedrockagentcore_gateway.this.gateway_arn
}

output "gateway_url" {
  description = "Control target base URL; append /invocations."
  value       = "${aws_bedrockagentcore_gateway.this.gateway_url}/${aws_bedrockagentcore_gateway_target.control.name}"
}
