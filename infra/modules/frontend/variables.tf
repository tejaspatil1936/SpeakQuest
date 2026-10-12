variable "project_name" {
  description = "Vercel project name; the production domain is <name>.vercel.app."
  type        = string
}

variable "api_url" {
  description = "HTTP API URL baked into the build as VITE_API_URL."
  type        = string
}

variable "demo_mode" {
  description = "Build with VITE_DEMO=1 (fixture data, clearly labelled) instead of the API."
  type        = bool
  default     = false
}

variable "web_dir" {
  description = "Path to the web app (the Vercel root directory)."
  type        = string
}
