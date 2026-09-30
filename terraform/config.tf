locals {
  defaults = jsondecode(file("${path.module}/defaults.json"))

  # PascalCase form of the environment for resources whose names AWS wants in that shape:
  # dev -> Dev, prod -> Prod, pr-123 -> Pr123. Every environment gets a distinct suffix.
  suffix = join("", [for part in split("-", var.env) : title(part)])

  base_configs = {
    dev = {
      bedrock_model_id   = local.defaults.bedrockModelId
      embedding_model_id = "amazon.titan-embed-text-v2:0"
      retain             = false # dev is disposable: destroy takes the stateful resources with it
      image_mutability   = "MUTABLE"
      log_retention_days = 7
      release_gate       = false
      ecs = {
        # Smallest Fargate size - dev serves one developer at a time.
        cpu                       = 256
        memory                    = 512
        desired_count             = 0
        min_healthy_percent       = 0
        max_healthy_percent       = 100
        circuit_breaker_rollback  = false
        az_rebalancing            = "DISABLED"
        health_check_grace_period = 60
        health_check_start_period = 20
        enable_execute_command    = true
        deregistration_delay      = 5
      }
    }

    prod = {
      bedrock_model_id   = "qwen.qwen3-235b-a22b-2507-v1:0"
      embedding_model_id = "amazon.titan-embed-text-v2:0"
      retain             = true
      image_mutability   = "IMMUTABLE"
      log_retention_days = 90
      release_gate       = true # agent versions are promoted by alvarog2491/agentcore-ab-release-gate
      ecs = {
        cpu                       = 256
        memory                    = 512
        desired_count             = 2
        min_healthy_percent       = 100
        max_healthy_percent       = 200
        circuit_breaker_rollback  = true
        az_rebalancing            = "ENABLED"
        health_check_grace_period = 120
        health_check_start_period = 60
        enable_execute_command    = false
        deregistration_delay      = 120
      }
    }
  }

  # staging is spread from prod so the two cannot drift, apart from the fields staging
  # deliberately overrides. It holds nothing that is not reproducible from this repo (the
  # documents are re-uploaded, the Knowledge Bases rebuilt on ingest), so nothing is retained
  # and the agent is deployed directly rather than through the release gate.
  env_configs = merge(local.base_configs, {
    staging = merge(local.base_configs.prod, {
      retain           = false
      image_mutability = "MUTABLE"
      release_gate     = false
    })
  })

  # Ephemeral pr-<n> environments inherit dev settings under a unique name.
  config = lookup(local.env_configs, var.env, local.env_configs.dev)

  ecs = merge(local.config.ecs, {
    desired_count = coalesce(var.ecs_desired_count, local.config.ecs.desired_count)
  })

  langfuse_base_url = var.langfuse_base_url != "" ? var.langfuse_base_url : local.defaults.langfuseBaseUrl

  # Origins the browser may upload PDFs from: the configured frontend origins plus the local
  # dev servers and Vercel previews (mirroring the API's CORS). S3 allows one wildcard per origin.
  upload_origins = distinct(concat(
    [for origin in split(",", var.cors_allow_origins) : trimspace(origin) if trimspace(origin) != ""],
    ["http://localhost:5173", "http://localhost:3000", "https://*.vercel.app"],
  ))
}
