variable "env" {
  description = "Environment name: dev, staging, prod, or an ephemeral pr-<number>."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env) || can(regex("^pr-[0-9]+$", var.env))
    error_message = "env must be dev, staging, prod or pr-<number>."
  }
}

variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "eu-central-1"
}

variable "agent_image_tag" {
  description = "ECR tag of the agent image the AgentCore runtime runs. For a release-gate-managed environment it only seeds the first version; the gate promotes later ones."
  type        = string
  default     = "placeholder"
}

variable "api_image_tag" {
  description = "ECR tag of the API image the ECS service runs."
  type        = string
  default     = "latest"
}

variable "cors_allow_origins" {
  description = "Comma-separated browser origins the API accepts."
  type        = string
  default     = "http://localhost:5173"
}

variable "langfuse_base_url" {
  description = "Langfuse host the agent reports to. Empty uses defaults.json."
  type        = string
  default     = ""
}

variable "ecs_desired_count" {
  description = "Override the environment's ECS desired task count (0 stops the API)."
  type        = number
  default     = null

  validation {
    condition     = var.ecs_desired_count == null || var.ecs_desired_count >= 0
    error_message = "ecs_desired_count must be a non-negative integer."
  }
}

variable "online_sampling_percentage" {
  description = "Share of live sessions the online evaluators score in release-gate environments."
  type        = number
  default     = 100
}
