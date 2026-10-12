variable "env" {
  description = "Deployment name; part of every resource name (speakquest-<env>-*)."
  type        = string
  default     = "dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,11}$", var.env))
    error_message = "env must be 2-12 lowercase letters, digits or dashes."
  }
}

variable "owner" {
  description = "Value of the owner tag on every resource."
  type        = string
}

variable "region" {
  description = "AWS region. Transcribe and the Bedrock model must be available here."
  type        = string
  default     = "us-east-1"
}

variable "alert_email" {
  description = "Receives AWS Budget and workflow-failure alerts."
  type        = string
  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "budget_limit_usd" {
  description = "Monthly budget; alerts fire at the thresholds below. An alert is not a cap."
  type        = number
  default     = 20
}

variable "budget_alert_thresholds_usd" {
  description = "Actual-spend alert levels in USD (system design §8.6: $5 and $15)."
  type        = list(number)
  default     = [5, 15]
}

variable "allowed_origins" {
  description = "Extra browser origins (e.g. Vercel preview URLs) for API and S3 CORS."
  type        = list(string)
  default     = []
}

variable "worker_runtime" {
  description = "Analysis worker runtime. Only \"lambda\" is implemented (see docs/DECISIONS.md)."
  type        = string
  default     = "lambda"
  validation {
    condition     = var.worker_runtime == "lambda"
    error_message = "Only the Lambda container worker is implemented; the Fargate/WhisperX fallback was not needed (docs/DECISIONS.md)."
  }
}

variable "worker_image_tag" {
  description = "Tag of the worker image in ECR, pushed by `make deploy`."
  type        = string
  default     = "latest"
}

variable "worker_image_digest" {
  description = "sha256 digest of the pushed worker image; pins the Lambda to exact bytes."
  type        = string
  default     = ""
}

variable "lambda_zip_path" {
  description = "Zip with the api/explain/persist code, built by `make build-lambda`."
  type        = string
  default     = "../build/lambda.zip"
}

variable "bedrock_model_id" {
  description = "Bedrock model or inference profile for coaching (a small, fast model)."
  type        = string
  default     = "us.amazon.nova-2-lite-v1:0"
}

variable "transcribe_language" {
  description = "Language code for Amazon Transcribe."
  type        = string
  default     = "en-US"
}

variable "log_retention_days" {
  description = "CloudWatch log retention for every log group Terraform creates."
  type        = number
  default     = 3
}

variable "api_throttle_rate" {
  description = "HTTP API stage steady-state requests per second."
  type        = number
  default     = 10
}

variable "api_throttle_burst" {
  description = "HTTP API stage burst."
  type        = number
  default     = 20
}

variable "enable_frontend" {
  description = "Create the Vercel project and deployment (needs VERCEL_API_TOKEN)."
  type        = bool
  default     = false
}

variable "vercel_team_id" {
  description = "Vercel team id; empty for a personal account."
  type        = string
  default     = ""
}

variable "vercel_project_name" {
  description = "Vercel project name."
  type        = string
  default     = ""
}

variable "frontend_demo_mode" {
  description = "Build the web app in demo mode (fixtures) instead of pointing it at the API."
  type        = bool
  default     = false
}
