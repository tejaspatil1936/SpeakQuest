# Vercel project, build-time environment and a production deployment, all in
# Terraform (system design §8.1 rule 1). The deployment uploads web/ (minus
# .vercelignore) and Vercel builds it; no Git integration is needed.
# The token is read from VERCEL_API_TOKEN in the shell.

locals {
  build_env = {
    VITE_API_URL = var.api_url
    VITE_DEMO    = var.demo_mode ? "1" : "0"
  }
}

resource "vercel_project" "web" {
  name             = var.project_name
  framework        = "vite"
  install_command  = "npm ci"
  build_command    = "npm run build"
  output_directory = "dist"
}

resource "vercel_project_environment_variable" "build" {
  for_each   = local.build_env
  project_id = vercel_project.web.id
  key        = each.key
  value      = each.value
  target     = ["production", "preview"]
  sensitive  = false # public by design: they end up in the browser bundle
}

data "vercel_project_directory" "web" {
  path = var.web_dir
}

resource "vercel_deployment" "production" {
  project_id  = vercel_project.web.id
  files       = data.vercel_project_directory.web.files
  path_prefix = data.vercel_project_directory.web.path
  production  = true
  environment = local.build_env

  depends_on = [vercel_project_environment_variable.build]
}
