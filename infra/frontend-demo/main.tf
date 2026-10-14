# Stand-alone Vercel deployment of the web app in demo mode.
#
# The full stack (infra/) needs AWS services that this project's AWS account
# is not permitted to create, so this root deploys only the frontend, built
# with VITE_DEMO=1: pre-analysed synthetic fixtures, labelled as such in the
# UI. It reuses the same module the full stack uses.
#
#   VERCEL_API_TOKEN=... terraform -chdir=infra/frontend-demo apply
#   VERCEL_API_TOKEN=... terraform -chdir=infra/frontend-demo destroy

terraform {
  required_version = ">= 1.10"
  required_providers {
    vercel = {
      source  = "vercel/vercel"
      version = "~> 5.20"
    }
  }
}

provider "vercel" {}

variable "project_name" {
  type    = string
  default = "speakquest-demo"
}

module "frontend" {
  source       = "../modules/frontend"
  project_name = var.project_name
  api_url      = ""
  demo_mode    = true
  web_dir      = "${path.root}/../../web"
}

output "deployment_url" {
  value = module.frontend.deployment_url
}

output "production_origin" {
  value = module.frontend.production_origin
}
