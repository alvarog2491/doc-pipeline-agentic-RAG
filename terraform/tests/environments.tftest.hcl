# Plan-level checks of the per-environment configuration. Providers are mocked, so no AWS
# credentials are needed and nothing is created: `terraform test`.

mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
  mock_data "aws_region" {
    defaults = {
      region = "eu-central-1"
    }
  }
  mock_data "aws_vpc" {
    defaults = {
      id = "vpc-12345678"
    }
  }
  mock_data "aws_subnets" {
    defaults = {
      ids = ["subnet-11111111", "subnet-22222222"]
    }
  }
}

mock_provider "archive" {}

run "dev_is_disposable_and_not_release_gated" {
  command = plan

  variables {
    env = "dev"
  }

  assert {
    condition     = output.release_gate_managed == false
    error_message = "dev deploys agent versions through Terraform, not the release gate"
  }

  assert {
    condition     = length(module.evaluations) == 0
    error_message = "online evaluators exist only in release-gate environments"
  }

  assert {
    condition     = local.ecs.desired_count == 0
    error_message = "dev keeps the API scaled to zero by default"
  }

  assert {
    condition     = local.config.retain == false
    error_message = "dev must not retain stateful resources"
  }
}

run "prod_is_release_gated_and_retains_state" {
  command = plan

  variables {
    env = "prod"
  }

  assert {
    condition     = output.release_gate_managed == true
    error_message = "prod agent versions are promoted by the release gate"
  }

  assert {
    condition     = length(module.evaluations) == 1
    error_message = "prod needs the online evaluators the gate scores against"
  }

  assert {
    condition     = local.config.retain == true && local.config.image_mutability == "IMMUTABLE"
    error_message = "prod retains state and uses immutable image tags"
  }

  assert {
    condition     = local.ecs.desired_count == 2
    error_message = "prod runs two API tasks"
  }
}

run "staging_is_derived_from_prod_with_deliberate_overrides" {
  command = plan

  variables {
    env = "staging"
  }

  assert {
    condition     = local.config.ecs == local.env_configs.prod.ecs
    error_message = "staging must share prod's ECS sizing"
  }

  assert {
    condition     = local.config.retain == false && local.config.release_gate == false && local.config.image_mutability == "MUTABLE"
    error_message = "staging overrides only retention, image mutability and the release gate"
  }
}

run "preview_environments_inherit_dev_under_a_unique_name" {
  command = plan

  variables {
    env = "pr-123"
  }

  assert {
    condition     = local.suffix == "Pr123"
    error_message = "the PascalCase suffix keeps preview resources from colliding"
  }

  assert {
    condition     = local.config == local.env_configs.dev
    error_message = "pr-* environments use dev settings"
  }
}

run "desired_count_can_be_overridden" {
  command = plan

  variables {
    env               = "prod"
    ecs_desired_count = 0
  }

  assert {
    condition     = local.ecs.desired_count == 0
    error_message = "ecs_desired_count must override the environment default, including zero"
  }
}

run "unknown_environments_are_rejected" {
  command = plan

  variables {
    env = "qa"
  }

  expect_failures = [var.env]
}

run "browser_uploads_are_allowed_from_the_frontend_origins_only" {
  command = plan

  variables {
    env                = "dev"
    cors_allow_origins = "https://app.example.com, http://localhost:5173"
  }

  assert {
    condition     = contains(local.upload_origins, "https://app.example.com") && contains(local.upload_origins, "https://*.vercel.app")
    error_message = "the configured frontend origin and Vercel previews must be allowed to upload"
  }

  assert {
    condition     = length(local.upload_origins) == length(distinct(local.upload_origins))
    error_message = "origins must be de-duplicated"
  }

  assert {
    condition     = !contains(local.upload_origins, "*")
    error_message = "the documents bucket must never accept uploads from every origin"
  }
}
