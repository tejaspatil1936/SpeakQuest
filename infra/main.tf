# SpeakQuest — every resource for one environment (system design §8).
# `make up` applies module.registry first (the worker image must exist
# before its Lambda), builds and pushes the image, then applies everything.

locals {
  name_prefix  = "speakquest-${var.env}"
  project_name = var.vercel_project_name != "" ? var.vercel_project_name : local.name_prefix
  # Known up front (not read back from the Vercel module) so CORS on the API
  # and bucket does not create a dependency cycle with the frontend.
  frontend_origin = "https://${local.project_name}.vercel.app"
  origins = distinct(compact(concat(
    ["http://localhost:5173"],
    var.enable_frontend ? [local.frontend_origin] : [],
    var.allowed_origins,
  )))
  common_env = {
    SPEAKQUEST_ENV             = var.env
    SPEAKQUEST_BACKEND         = "aws"
    SPEAKQUEST_BUCKET          = module.storage.bucket_name
    SPEAKQUEST_TABLE           = module.data.table_name
    SPEAKQUEST_LANGUAGE        = var.transcribe_language
    SPEAKQUEST_ALLOWED_ORIGINS = join(",", local.origins)
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.root}/../build/lambda"
  output_path = "${path.root}/${var.lambda_zip_path}"
}

module "storage" {
  source          = "./modules/storage"
  name_prefix     = local.name_prefix
  allowed_origins = local.origins
}

module "data" {
  source      = "./modules/data"
  name_prefix = local.name_prefix
}

module "registry" {
  source      = "./modules/registry"
  name_prefix = local.name_prefix
}

module "ai" {
  source           = "./modules/ai"
  name_prefix      = local.name_prefix
  region           = var.region
  bucket_arn       = module.storage.bucket_arn
  bedrock_model_id = var.bedrock_model_id
}

module "worker" {
  source             = "./modules/worker"
  name_prefix        = local.name_prefix
  repository_url     = module.registry.repository_url
  image_tag          = var.worker_image_tag
  image_digest       = var.worker_image_digest
  bucket_arn         = module.storage.bucket_arn
  table_arn          = module.data.table_arn
  common_env         = local.common_env
  log_retention_days = var.log_retention_days
}

module "workflow" {
  source                 = "./modules/workflow"
  name_prefix            = local.name_prefix
  bucket_name            = module.storage.bucket_name
  bucket_arn             = module.storage.bucket_arn
  table_arn              = module.data.table_arn
  worker_function_arn    = module.worker.function_arn
  lambda_zip_path        = data.archive_file.lambda.output_path
  lambda_zip_hash        = data.archive_file.lambda.output_base64sha256
  common_env             = local.common_env
  bedrock_model_id       = var.bedrock_model_id
  bedrock_policy_json    = module.ai.bedrock_policy_json
  transcribe_policy_json = module.ai.transcribe_policy_json
  log_retention_days     = var.log_retention_days
}

module "api" {
  source             = "./modules/api"
  name_prefix        = local.name_prefix
  bucket_arn         = module.storage.bucket_arn
  table_arn          = module.data.table_arn
  state_machine_arn  = module.workflow.state_machine_arn
  lambda_zip_path    = data.archive_file.lambda.output_path
  lambda_zip_hash    = data.archive_file.lambda.output_base64sha256
  common_env         = local.common_env
  allowed_origins    = local.origins
  throttle_rate      = var.api_throttle_rate
  throttle_burst     = var.api_throttle_burst
  log_retention_days = var.log_retention_days
}

module "observability" {
  source               = "./modules/observability"
  name_prefix          = local.name_prefix
  alert_email          = var.alert_email
  limit_usd            = var.budget_limit_usd
  alert_thresholds_usd = var.budget_alert_thresholds_usd
  state_machine_arn    = module.workflow.state_machine_arn
  api_id               = module.api.api_id
}

module "frontend" {
  count        = var.enable_frontend ? 1 : 0
  source       = "./modules/frontend"
  project_name = local.project_name
  api_url      = module.api.api_url
  demo_mode    = var.frontend_demo_mode
  web_dir      = "${path.root}/../web"
}
