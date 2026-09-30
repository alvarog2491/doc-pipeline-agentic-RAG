variable "env" {
  type = string
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "alb" {
  name_prefix = "doc-pipeline-${var.env}-alb-"
  description = "Public HTTP access to the Doc Pipeline API load balancer"
  vpc_id      = data.aws_vpc.default.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from CloudFront and developers"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.alb.id
  description       = "Reach the API tasks"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_lb" "this" {
  name                       = "doc-pipeline-${var.env}"
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = data.aws_subnets.default.ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  # Server-Sent Events stay open while the agent thinks; the API sends a keep-alive comment
  # every 15 s, so this only bounds a genuinely stalled connection.
  idle_timeout = 300
}

output "alb_arn" {
  value = aws_lb.this.arn
}

output "dns_name" {
  value = aws_lb.this.dns_name
}

output "security_group_id" {
  value = aws_security_group.alb.id
}

output "vpc_id" {
  value = data.aws_vpc.default.id
}

output "subnet_ids" {
  value = data.aws_subnets.default.ids
}
