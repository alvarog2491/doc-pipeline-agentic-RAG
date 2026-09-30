module "ecr" {
  source = "./modules/ecr"

  env                  = var.env
  image_tag_mutability = local.config.image_mutability
  force_delete         = !local.config.retain
}

module "data" {
  source = "./modules/data"

  env                = var.env
  suffix             = local.suffix
  retain             = local.config.retain
  embedding_model_id = local.config.embedding_model_id
  log_retention_days = local.config.log_retention_days
  cors_allow_origins = local.upload_origins
}

module "agentcore" {
  source = "./modules/agentcore"

  env                  = var.env
  suffix               = local.suffix
  agent_repository_url = module.ecr.repository_urls["agent"]
  agent_repository_arn = module.ecr.repository_arns["agent"]
  image_tag            = var.agent_image_tag
  bedrock_model_id     = local.config.bedrock_model_id
  bedrock_router_model = local.defaults.bedrockRouterModelId
  bedrock_temperature  = local.defaults.bedrockTemperature
  langfuse_base_url    = local.langfuse_base_url
  release_gate_managed = local.config.release_gate
}

module "evaluations" {
  source = "./modules/evaluations"
  count  = local.config.release_gate ? 1 : 0

  env                = var.env
  suffix             = local.suffix
  runtime_id         = module.agentcore.runtime_id
  runtime_name       = module.agentcore.runtime_name
  sampling_percent   = var.online_sampling_percentage
  log_retention_days = local.config.log_retention_days
}

module "alb" {
  source = "./modules/alb"

  env = var.env
}

module "ecs" {
  source = "./modules/ecs"

  env                   = var.env
  region                = var.region
  vpc_id                = module.alb.vpc_id
  subnet_ids            = module.alb.subnet_ids
  alb_arn               = module.alb.alb_arn
  alb_security_group_id = module.alb.security_group_id
  repository_url        = module.ecr.repository_urls["api"]
  repository_arn        = module.ecr.repository_arns["api"]
  image_tag             = var.api_image_tag
  gateway_arn           = module.agentcore.gateway_arn
  gateway_url           = module.agentcore.gateway_url
  registry_table_name   = module.data.registry_table_name
  registry_table_arn    = module.data.registry_table_arn
  documents_bucket_name = module.data.documents_bucket_name
  documents_bucket_arn  = module.data.documents_bucket_arn
  cors_allow_origins    = var.cors_allow_origins
  ecs                   = local.ecs
  retain                = local.config.retain
  log_retention_days    = local.config.log_retention_days
}

module "cloudfront" {
  source = "./modules/cloudfront"

  env          = var.env
  alb_dns_name = module.alb.dns_name
}
