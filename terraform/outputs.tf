output "env" {
  value = var.env
}

output "agent_repository_url" {
  description = "ECR repository for the agent image."
  value       = module.ecr.repository_urls["agent"]
}

output "api_repository_url" {
  description = "ECR repository for the API image."
  value       = module.ecr.repository_urls["api"]
}

output "documents_bucket" {
  description = "Upload PDFs under uploads/ in this bucket."
  value       = module.data.documents_bucket_name
}

output "registry_table" {
  description = "DynamoDB registry of ingested documents."
  value       = module.data.registry_table_name
}

output "vector_bucket" {
  value = module.data.vector_bucket_name
}

output "runtime_id" {
  value = module.agentcore.runtime_id
}

output "runtime_arn" {
  value = module.agentcore.runtime_arn
}

output "gateway_id" {
  description = "Gateway identifier the release gate routes traffic through."
  value       = module.agentcore.gateway_id
}

output "gateway_arn" {
  value = module.agentcore.gateway_arn
}

output "gateway_url" {
  description = "Control target base URL; append /invocations."
  value       = module.agentcore.gateway_url
}

output "cluster_name" {
  value = module.ecs.cluster_name
}

output "service_name" {
  value = module.ecs.service_name
}

output "alb_dns_name" {
  value = module.alb.dns_name
}

output "cloudfront_domain" {
  description = "HTTPS endpoint for the hosted frontend: VITE_API_URL=https://<domain>."
  value       = module.cloudfront.domain_name
}

output "release_gate_managed" {
  description = "True when the release gate, not Terraform, promotes agent versions."
  value       = local.config.release_gate
}

output "evaluation_config_id" {
  description = "Enabled online-evaluation template the release gate copies (release-gate environments only)."
  value       = try(module.evaluations[0].evaluation_config_id, "")
}

output "ab_test_role_arn" {
  description = "Role AgentCore assumes to run the A/B test (release-gate environments only)."
  value       = try(module.evaluations[0].ab_test_role_arn, "")
}

output "quality_gates" {
  description = "JSON evaluator-id -> minimum score, for the release gate's quality-gates input."
  value       = try(module.evaluations[0].quality_gates_json, "{}")
}
