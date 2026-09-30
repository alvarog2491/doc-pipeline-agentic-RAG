variable "env" {
  type = string
}

variable "suffix" {
  type = string
}

variable "runtime_id" {
  type = string
}

variable "runtime_name" {
  type = string
}

variable "sampling_percent" {
  type = number
}

variable "log_retention_days" {
  type = number
}

variable "session_timeout_minutes" {
  description = "Idle time after which a session counts as finished and is scored."
  type        = number
  default     = 1
}

variable "quality_gate_minimums" {
  description = "Minimum treatment mean per evaluator for the release gate to promote."
  type        = map(number)
  default = {
    ErrorFree         = 0.95
    LatencyBudget     = 0.90
    GroundedRetrieval = 0.95
    RetrievalBudget   = 0.95
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region

  # The data source AgentCore derives for a runtime endpoint: its log group and service name.
  log_group_names = ["/aws/bedrock-agentcore/runtimes/${var.runtime_id}-control"]
  service_names   = ["${var.runtime_name}.control"]
}

# ---------------------------------------------------------------- evaluator Lambda
data "archive_file" "evaluators" {
  type        = "zip"
  source_dir  = "${path.module}/../../../apps/online-evaluators"
  output_path = "${path.module}/.build/online-evaluators.zip"
  excludes    = ["tests", "**/__pycache__", ".pytest_cache", "pyproject.toml"]
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "evaluator_lambda" {
  name_prefix        = "doc-pipeline-${var.env}-evaluators-"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "evaluator_lambda_logs" {
  role       = aws_iam_role.evaluator_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "evaluator_lambda" {
  name              = "/aws/lambda/doc-pipeline-${var.env}-online-evaluators"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "evaluators" {
  function_name    = "doc-pipeline-${var.env}-online-evaluators"
  role             = aws_iam_role.evaluator_lambda.arn
  runtime          = "python3.12"
  handler          = "online_evaluators.handler.lambda_handler"
  filename         = data.archive_file.evaluators.output_path
  source_code_hash = data.archive_file.evaluators.output_base64sha256
  timeout          = 60
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.evaluator_lambda, aws_iam_role_policy_attachment.evaluator_lambda_logs]
}

resource "aws_lambda_permission" "agentcore" {
  statement_id   = "AllowAgentCoreEvaluations"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.evaluators.function_name
  principal      = "bedrock-agentcore.amazonaws.com"
  source_account = local.account_id
}

# ---------------------------------------------------------------- evaluators (no LLM judge)
# Each evaluator is the same Lambda registered under a different name; the handler picks the
# check by name. Scoring a session therefore costs one Lambda invocation, not model tokens.
resource "aws_bedrockagentcore_evaluator" "this" {
  for_each = var.quality_gate_minimums

  evaluator_name = "${each.key}${var.suffix}"
  description    = "Deterministic ${each.key} check over the session's OpenTelemetry spans"
  level          = "SESSION"

  evaluator_config {
    code_based {
      lambda_config {
        lambda_arn                = aws_lambda_function.evaluators.arn
        lambda_timeout_in_seconds = 60
      }
    }
  }

  depends_on = [aws_lambda_permission.agentcore]
}

# ---------------------------------------------------------------- online evaluation
data "aws_iam_policy_document" "evaluation_trust" {
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

data "aws_iam_policy_document" "evaluation" {
  statement {
    sid     = "ReadRuntimeTelemetry"
    actions = ["logs:DescribeLogGroups", "logs:DescribeIndexPolicies", "logs:PutIndexPolicy", "logs:StartQuery", "logs:GetQueryResults", "logs:StopQuery", "logs:FilterLogEvents", "logs:GetLogEvents"]
    resources = [
      "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
      "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*",
      "arn:aws:logs:${local.region}:${local.account_id}:log-group:aws/spans",
      "arn:aws:logs:${local.region}:${local.account_id}:log-group:aws/spans:*",
    ]
  }
  statement {
    sid       = "WriteEvaluationResults"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*"]
  }
  statement {
    sid       = "InvokeCodeEvaluators"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.evaluators.arn]
  }
  statement {
    sid       = "ReadEvaluators"
    actions   = ["bedrock-agentcore:GetEvaluator"]
    resources = ["arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:evaluator/*"]
  }
}

resource "aws_iam_role" "evaluation" {
  name_prefix        = "doc-pipeline-${var.env}-online-eval-"
  assume_role_policy = data.aws_iam_policy_document.evaluation_trust.json
}

resource "aws_iam_role_policy" "evaluation" {
  role   = aws_iam_role.evaluation.id
  policy = data.aws_iam_policy_document.evaluation.json
}

# The template the release gate copies for the control and candidate variants. It stays
# enabled, so the control endpoint is also scored continuously between releases.
resource "aws_bedrockagentcore_online_evaluation_config" "template" {
  online_evaluation_config_name = "DocPipelineGate${var.suffix}"
  description                   = "Deterministic online evaluators for the release gate"
  enable_on_create              = true
  execution_status              = "ENABLED"
  evaluation_execution_role_arn = aws_iam_role.evaluation.arn

  data_source_config {
    cloudwatch_logs {
      log_group_names = local.log_group_names
      service_names   = local.service_names
    }
  }

  dynamic "evaluator" {
    for_each = aws_bedrockagentcore_evaluator.this
    content {
      evaluator_id = evaluator.value.evaluator_id
    }
  }

  rule {
    sampling_config {
      sampling_percentage = var.sampling_percent
    }
    session_config {
      session_timeout_minutes = var.session_timeout_minutes
    }
  }

  depends_on = [aws_iam_role_policy.evaluation]
}

# ---------------------------------------------------------------- A/B test role
data "aws_iam_policy_document" "ab_test_trust" {
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
      values   = ["arn:aws:bedrock-agentcore:*:${local.account_id}:ab-test/*"]
    }
  }
}

data "aws_iam_policy_document" "ab_test" {
  statement {
    sid = "RouteAndEvaluate"
    actions = [
      "bedrock-agentcore:GetGateway",
      "bedrock-agentcore:GetGatewayTarget",
      "bedrock-agentcore:ListGatewayTargets",
      "bedrock-agentcore:CreateGatewayRule",
      "bedrock-agentcore:UpdateGatewayRule",
      "bedrock-agentcore:GetGatewayRule",
      "bedrock-agentcore:DeleteGatewayRule",
      "bedrock-agentcore:ListGatewayRules",
      "bedrock-agentcore:GetOnlineEvaluationConfig",
      "bedrock-agentcore:GetEvaluator",
    ]
    resources = ["arn:aws:bedrock-agentcore:*:${local.account_id}:*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceAccount"
      values   = [local.account_id]
    }
  }
  statement {
    sid       = "DescribeLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }
  statement {
    sid     = "QueryTelemetry"
    actions = ["logs:DescribeIndexPolicies", "logs:PutIndexPolicy", "logs:StartQuery", "logs:GetQueryResults", "logs:StopQuery", "logs:FilterLogEvents", "logs:GetLogEvents"]
    resources = [
      "arn:aws:logs:*:${local.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*",
      "arn:aws:logs:*:${local.account_id}:log-group:aws/spans",
      "arn:aws:logs:*:${local.account_id}:log-group:aws/spans:*",
    ]
  }
}

resource "aws_iam_role" "ab_test" {
  name_prefix        = "doc-pipeline-${var.env}-ab-test-"
  assume_role_policy = data.aws_iam_policy_document.ab_test_trust.json
  description        = "Allows AgentCore A/B tests to route and evaluate live traffic"
}

resource "aws_iam_role_policy" "ab_test" {
  role   = aws_iam_role.ab_test.id
  policy = data.aws_iam_policy_document.ab_test.json
}

output "evaluation_config_id" {
  value = aws_bedrockagentcore_online_evaluation_config.template.online_evaluation_config_id
}

output "ab_test_role_arn" {
  value = aws_iam_role.ab_test.arn
}

output "evaluator_ids" {
  value = { for name, evaluator in aws_bedrockagentcore_evaluator.this : name => evaluator.evaluator_id }
}

output "quality_gates_json" {
  description = "evaluator id -> minimum score, in the release gate's quality-gates format"
  value = jsonencode({
    for name, evaluator in aws_bedrockagentcore_evaluator.this :
    evaluator.evaluator_id => var.quality_gate_minimums[name]
  })
}
