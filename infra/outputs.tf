output "api_url" {
  description = "HTTP API invoke URL (the web app's VITE_API_URL)."
  value       = module.api.api_url
}

output "bucket_name" {
  value = module.storage.bucket_name
}

output "table_name" {
  value = module.data.table_name
}

output "ecr_repository_url" {
  value = module.registry.repository_url
}

output "state_machine_arn" {
  value = module.workflow.state_machine_arn
}

output "worker_function_name" {
  value = module.worker.function_name
}

output "frontend_url" {
  value = var.enable_frontend ? module.frontend[0].production_origin : null
}

output "region" {
  value = var.region
}
