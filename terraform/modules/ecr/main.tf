variable "env" {
  type = string
}

variable "image_tag_mutability" {
  type = string
}

variable "force_delete" {
  description = "Delete repositories even when they still hold images (disposable environments only)."
  type        = bool
}

locals {
  repositories = toset(["agent", "api"])
}

resource "aws_ecr_repository" "this" {
  for_each = local.repositories

  name                 = "doc-pipeline-${each.key}-${var.env}"
  image_tag_mutability = var.image_tag_mutability
  force_delete         = var.force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain only the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "repository_urls" {
  value = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "repository_arns" {
  value = { for name, repo in aws_ecr_repository.this : name => repo.arn }
}
