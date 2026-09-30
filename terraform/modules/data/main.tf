variable "env" {
  type = string
}

variable "suffix" {
  type = string
}

variable "retain" {
  description = "Keep stateful resources on destroy (production)."
  type        = bool
}

variable "embedding_model_id" {
  type = string
}

variable "log_retention_days" {
  type = number
}

variable "cors_allow_origins" {
  description = "Browser origins allowed to upload PDFs straight to the documents bucket with a presigned POST."
  type        = list(string)
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id          = data.aws_caller_identity.current.account_id
  region              = data.aws_region.current.region
  partition           = "aws"
  embedding_model_arn = "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.embedding_model_id}"
}

# ---------------------------------------------------------------- documents bucket
# Users upload PDFs under uploads/. The bucket is private: the API presigns short-lived
# links for the pages an answer cites.
resource "aws_s3_bucket" "documents" {
  bucket        = "doc-pipeline-docs-${var.env}-${local.account_id}"
  force_destroy = !var.retain
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# The frontend uploads PDFs directly to S3 (presigned POST from the API), so the bucket must
# accept cross-origin POSTs from it. Nothing else is opened: reads use presigned GET links
# that are opened in an iframe, which needs no CORS.
resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = var.cors_allow_origins
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

data "aws_iam_policy_document" "documents_tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = data.aws_iam_policy_document.documents_tls.json
}

# ---------------------------------------------------------------- vectors + registry
# One S3 Vectors index per document lives in this bucket; the ingestion Lambda creates it.
resource "aws_s3vectors_vector_bucket" "vectors" {
  vector_bucket_name = "doc-pipeline-vectors-${var.env}-${local.account_id}"
  force_destroy      = !var.retain
}

resource "aws_dynamodb_table" "registry" {
  name         = "doc-pipeline-registry-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"

  attribute {
    name = "doc_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.retain
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = var.retain
}

# ---------------------------------------------------------------- Textract plumbing
# Textract only publishes to topics whose name starts with "AmazonTextract".
resource "aws_sns_topic" "textract" {
  name = "AmazonTextract-doc-pipeline-${var.env}"
}

data "aws_iam_policy_document" "textract_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["textract.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "textract_publish" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.textract.arn]
  }
}

resource "aws_iam_role" "textract" {
  name_prefix        = "doc-pipeline-${var.env}-textract-"
  assume_role_policy = data.aws_iam_policy_document.textract_trust.json
}

resource "aws_iam_role_policy" "textract" {
  role   = aws_iam_role.textract.id
  policy = data.aws_iam_policy_document.textract_publish.json
}

# ---------------------------------------------------------------- Knowledge Base role
# One service role is shared by every per-document Knowledge Base the Lambda creates.
data "aws_iam_policy_document" "kb_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:bedrock:${local.region}:${local.account_id}:knowledge-base/*"]
    }
  }
}

data "aws_iam_policy_document" "kb_permissions" {
  statement {
    sid       = "EmbedChunksAndQueries"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.embedding_model_arn]
  }
  statement {
    sid       = "ReadStagedPages"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.documents.arn}/kb-input/*"]
  }
  statement {
    sid       = "ListStagedPages"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["kb-input/*"]
    }
  }
  statement {
    sid = "StoreAndSearchVectors"
    actions = [
      "s3vectors:GetIndex",
      "s3vectors:QueryVectors",
      "s3vectors:PutVectors",
      "s3vectors:GetVectors",
      "s3vectors:DeleteVectors",
      "s3vectors:ListVectors",
    ]
    resources = [
      aws_s3vectors_vector_bucket.vectors.vector_bucket_arn,
      "${aws_s3vectors_vector_bucket.vectors.vector_bucket_arn}/index/*",
    ]
  }
}

resource "aws_iam_role" "kb" {
  name_prefix        = "doc-pipeline-${var.env}-kb-"
  assume_role_policy = data.aws_iam_policy_document.kb_trust.json
}

resource "aws_iam_role_policy" "kb" {
  role   = aws_iam_role.kb.id
  policy = data.aws_iam_policy_document.kb_permissions.json
}

# ---------------------------------------------------------------- ingestion Lambdas
data "archive_file" "ingestion" {
  type        = "zip"
  source_dir  = "${path.module}/../../../apps/ingestion"
  output_path = "${path.module}/.build/ingestion.zip"
  excludes    = ["tests", "**/__pycache__", ".pytest_cache", "pyproject.toml", "README.md"]
}

locals {
  common_environment = {
    ENV                = var.env
    REGISTRY_TABLE     = aws_dynamodb_table.registry.name
    VECTOR_BUCKET      = aws_s3vectors_vector_bucket.vectors.vector_bucket_name
    KB_ROLE_ARN        = aws_iam_role.kb.arn
    EMBEDDING_MODEL_ID = var.embedding_model_id
    TEXTRACT_TOPIC_ARN = aws_sns_topic.textract.arn
    TEXTRACT_ROLE_ARN  = aws_iam_role.textract.arn
  }

  registry_write = {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.registry.arn]
  }
  kb_admin_actions = [
    "bedrock:CreateKnowledgeBase",
    "bedrock:GetKnowledgeBase",
    "bedrock:ListKnowledgeBases",
    "bedrock:DeleteKnowledgeBase",
    "bedrock:CreateDataSource",
    "bedrock:ListDataSources",
    "bedrock:DeleteDataSource",
    "bedrock:StartIngestionJob",
    "bedrock:GetIngestionJob",
    "bedrock:TagResource",
  ]
  vector_index_arn = "${aws_s3vectors_vector_bucket.vectors.vector_bucket_arn}/index/*"

  # Staged per-page Markdown that Bedrock chunks and embeds; distinct from uploads/, so
  # writing it never re-triggers the pipeline.
  staged_pages = [
    {
      actions   = ["s3:PutObject", "s3:DeleteObject"]
      resources = ["${aws_s3_bucket.documents.arn}/kb-input/*"]
    },
    {
      actions   = ["s3:ListBucket"]
      resources = [aws_s3_bucket.documents.arn]
    },
  ]

  functions = {
    start_extraction = {
      handler     = "ingestion.handlers.start_extraction"
      timeout     = 60
      memory_size = 256
      statements = [
        {
          actions   = ["textract:StartDocumentAnalysis"]
          resources = ["*"]
        },
        {
          actions   = ["s3:GetObject"]
          resources = ["${aws_s3_bucket.documents.arn}/uploads/*"]
        },
        {
          actions   = ["iam:PassRole"]
          resources = [aws_iam_role.textract.arn]
        },
        local.registry_write,
      ]
    }
    process_result = {
      handler     = "ingestion.handlers.process_result"
      timeout     = 900
      memory_size = 1024
      statements = [
        {
          actions   = ["textract:GetDocumentAnalysis"]
          resources = ["*"]
        },
        {
          actions   = local.kb_admin_actions
          resources = ["*"]
        },
        {
          actions   = ["s3vectors:CreateIndex", "s3vectors:GetIndex", "s3vectors:ListIndexes"]
          resources = [aws_s3vectors_vector_bucket.vectors.vector_bucket_arn, local.vector_index_arn]
        },
        {
          actions   = ["iam:PassRole"]
          resources = [aws_iam_role.kb.arn]
        },
        local.registry_write,
        local.staged_pages[0],
        local.staged_pages[1],
      ]
    }
    check_ingestion = {
      handler     = "ingestion.handlers.check_ingestion"
      timeout     = 120
      memory_size = 256
      statements = [
        {
          actions   = ["bedrock:GetIngestionJob"]
          resources = ["*"]
        },
        {
          actions   = ["dynamodb:Scan", "dynamodb:UpdateItem"]
          resources = [aws_dynamodb_table.registry.arn]
        },
      ]
    }
    on_delete = {
      handler     = "ingestion.handlers.on_delete"
      timeout     = 300
      memory_size = 256
      statements = [
        {
          actions   = local.kb_admin_actions
          resources = ["*"]
        },
        {
          actions   = ["s3vectors:DeleteIndex", "s3vectors:GetIndex"]
          resources = [aws_s3vectors_vector_bucket.vectors.vector_bucket_arn, local.vector_index_arn]
        },
        local.registry_write,
        local.staged_pages[0],
        local.staged_pages[1],
      ]
    }
  }
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

data "aws_iam_policy_document" "function" {
  for_each = local.functions

  dynamic "statement" {
    for_each = each.value.statements
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role" "function" {
  for_each = local.functions

  name_prefix        = "doc-pipeline-${var.env}-${replace(each.key, "_", "-")}-"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "function" {
  for_each = local.functions

  role   = aws_iam_role.function[each.key].id
  policy = data.aws_iam_policy_document.function[each.key].json
}

resource "aws_iam_role_policy_attachment" "function_logs" {
  for_each = local.functions

  role       = aws_iam_role.function[each.key].name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "function" {
  for_each = local.functions

  name              = "/aws/lambda/doc-pipeline-${var.env}-${replace(each.key, "_", "-")}"
  retention_in_days = var.log_retention_days
}

# Asynchronous invocations that still fail after Lambda's retries land here for inspection.
resource "aws_sqs_queue" "dlq" {
  name                      = "doc-pipeline-${var.env}-ingestion-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

data "aws_iam_policy_document" "dlq_send" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "dlq_send" {
  for_each = local.functions

  name   = "dlq-send"
  role   = aws_iam_role.function[each.key].id
  policy = data.aws_iam_policy_document.dlq_send.json
}

resource "aws_lambda_function" "ingestion" {
  for_each = local.functions

  function_name    = "doc-pipeline-${var.env}-${replace(each.key, "_", "-")}"
  role             = aws_iam_role.function[each.key].arn
  runtime          = "python3.12"
  handler          = each.value.handler
  filename         = data.archive_file.ingestion.output_path
  source_code_hash = data.archive_file.ingestion.output_base64sha256
  timeout          = each.value.timeout
  memory_size      = each.value.memory_size

  environment {
    variables = local.common_environment
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  depends_on = [
    aws_cloudwatch_log_group.function,
    aws_iam_role_policy.dlq_send,
    aws_iam_role_policy_attachment.function_logs,
  ]
}

# ---------------------------------------------------------------- triggers
resource "aws_lambda_permission" "s3" {
  for_each = toset(["start_extraction", "on_delete"])

  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.ingestion[each.key].function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.documents.arn
  source_account = local.account_id
}

resource "aws_lambda_permission" "sns" {
  statement_id  = "AllowTextractCompletion"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion["process_result"].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.textract.arn
}

# Bedrock's ingestion job (chunk, embed, store) can outlast a Lambda, so process_result only
# starts it; this tick finishes any document whose job has ended.
resource "aws_cloudwatch_event_rule" "check_ingestion" {
  name                = "doc-pipeline-${var.env}-check-ingestion"
  description         = "Finish documents whose Bedrock ingestion job has ended"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "check_ingestion" {
  rule = aws_cloudwatch_event_rule.check_ingestion.name
  arn  = aws_lambda_function.ingestion["check_ingestion"].arn
}

resource "aws_lambda_permission" "events" {
  statement_id  = "AllowScheduledCheck"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion["check_ingestion"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.check_ingestion.arn
}

resource "aws_sns_topic_subscription" "process_result" {
  topic_arn = aws_sns_topic.textract.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.ingestion["process_result"].arn
}

# A PDF dropped under uploads/ starts the pipeline; deleting it tears its Knowledge Base down.
resource "aws_s3_bucket_notification" "documents" {
  bucket = aws_s3_bucket.documents.id

  dynamic "lambda_function" {
    for_each = { for pair in setproduct(["created", "removed"], [".pdf", ".PDF"]) : "${pair[0]}${pair[1]}" => pair }
    content {
      lambda_function_arn = aws_lambda_function.ingestion[lambda_function.value[0] == "created" ? "start_extraction" : "on_delete"].arn
      events              = [lambda_function.value[0] == "created" ? "s3:ObjectCreated:*" : "s3:ObjectRemoved:*"]
      filter_prefix       = "uploads/"
      filter_suffix       = lambda_function.value[1]
    }
  }

  depends_on = [aws_lambda_permission.s3]
}

output "documents_bucket_name" {
  value = aws_s3_bucket.documents.bucket
}

output "documents_bucket_arn" {
  value = aws_s3_bucket.documents.arn
}

output "registry_table_name" {
  value = aws_dynamodb_table.registry.name
}

output "registry_table_arn" {
  value = aws_dynamodb_table.registry.arn
}

output "vector_bucket_name" {
  value = aws_s3vectors_vector_bucket.vectors.vector_bucket_name
}

output "kb_role_arn" {
  value = aws_iam_role.kb.arn
}

output "ingestion_function_names" {
  value = { for key, fn in aws_lambda_function.ingestion : key => fn.function_name }
}
