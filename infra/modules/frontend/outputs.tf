output "production_origin" {
  description = "Vercel production domain (<project>.vercel.app)."
  value       = "https://${var.project_name}.vercel.app"
}

output "deployment_url" {
  value = "https://${vercel_deployment.production.url}"
}

output "project_id" {
  value = vercel_project.web.id
}
