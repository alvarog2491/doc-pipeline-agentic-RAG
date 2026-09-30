variable "env" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "alb_arn" {
  type = string
}

variable "alb_security_group_id" {
  type = string
}

variable "repository_url" {
  type = string
}

variable "repository_arn" {
  type = string
}

variable "image_tag" {
  type = string
}

variable "gateway_arn" {
  type = string
}

variable "gateway_url" {
  type = string
}

variable "registry_table_name" {
  type = string
}

variable "registry_table_arn" {
  type = string
}

variable "documents_bucket_name" {
  type = string
}

variable "documents_bucket_arn" {
  type = string
}

variable "cors_allow_origins" {
  type = string
}

variable "retain" {
  type = bool
}

variable "log_retention_days" {
  type = number
}

variable "ecs" {
  description = "Task sizing and rollout settings; cpu/memory must be a valid Fargate pair."
  type = object({
    cpu                       = number
    memory                    = number
    desired_count             = number
    min_healthy_percent       = number
    max_healthy_percent       = number
    circuit_breaker_rollback  = bool
    az_rebalancing            = string
    health_check_grace_period = number
    health_check_start_period = number
    enable_execute_command    = bool
    deregistration_delay      = number
  })
}

locals {
  name = "doc-pipeline-api-${var.env}"
}

resource "aws_ecs_cluster" "this" {
  name = "doc-pipeline-${var.env}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/api-${var.env}"
  retention_in_days = var.log_retention_days
  skip_destroy      = var.retain
}

data "aws_iam_policy_document" "ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name_prefix        = "${local.name}-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_pull" {
  statement {
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [var.repository_arn]
  }
}

resource "aws_iam_role_policy" "execution_pull" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_pull.json
}

resource "aws_iam_role" "task" {
  name_prefix        = "${local.name}-task-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks.json
}

# The API needs exactly four things: invoke the Gateway, read the document registry, presign
# links to the uploaded PDFs, and presign browser uploads into uploads/. No login or user store exists (see AGENTS.md).
data "aws_iam_policy_document" "task" {
  statement {
    sid       = "InvokeGateway"
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [var.gateway_arn]
  }
  statement {
    sid       = "ReadRegistry"
    actions   = ["dynamodb:Scan"]
    resources = [var.registry_table_arn]
  }
  statement {
    sid       = "PresignCitedDocuments"
    actions   = ["s3:GetObject"]
    resources = ["${var.documents_bucket_arn}/uploads/*"]
  }
  statement {
    # Presigned POSTs are signed with the task role, so it must be allowed to write what it
    # authorises; the policy in each ticket then narrows that to one key and a size limit.
    sid       = "PresignPdfUploads"
    actions   = ["s3:PutObject"]
    resources = ["${var.documents_bucket_arn}/uploads/*"]
  }
}

resource "aws_iam_role_policy" "task" {
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_ecs_task_definition" "api" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs.cpu
  memory                   = var.ecs.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${var.repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "AGENT_GATEWAY_URL", value = var.gateway_url },
      { name = "AWS_REGION", value = var.region },
      { name = "CORS_ALLOW_ORIGINS", value = var.cors_allow_origins },
      { name = "REGISTRY_TABLE", value = var.registry_table_name },
      { name = "DOCUMENTS_BUCKET", value = var.documents_bucket_name },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = var.ecs.health_check_start_period
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
        "mode"                  = "blocking"
      }
    }
  }])
}

resource "aws_security_group" "service" {
  name_prefix = "${local.name}-"
  description = "API tasks: reachable only from the load balancer"
  vpc_id      = var.vpc_id

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "from_alb" {
  security_group_id            = aws_security_group.service.id
  description                  = "API port from the load balancer"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = var.alb_security_group_id
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.service.id
  description       = "Reach the Gateway, DynamoDB, S3 and ECR"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_lb_target_group" "api" {
  name_prefix          = "dpapi-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = var.ecs.deregistration_delay

  health_check {
    path = "/health"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = var.alb_arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name                               = local.name
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.api.arn
  desired_count                      = var.ecs.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = var.ecs.min_healthy_percent
  deployment_maximum_percent         = var.ecs.max_healthy_percent
  availability_zone_rebalancing      = var.ecs.az_rebalancing
  health_check_grace_period_seconds  = var.ecs.health_check_grace_period
  enable_execute_command             = var.ecs.enable_execute_command

  deployment_circuit_breaker {
    enable   = true
    rollback = var.ecs.circuit_breaker_rollback
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http, aws_iam_role_policy.execution_pull]
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.api.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.api.family
}
