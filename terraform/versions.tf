terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.60"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Partial configuration: `docpipe deploy` (and CI) pass envs/<env>.backend.hcl, so every
  # environment keeps its own state object in the state bucket created by ./bootstrap.
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "doc-pipeline-agentic-rag"
      Environment = var.env
      ManagedBy   = "terraform"
    }
  }
}
