variable "name_prefix" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "bucket_arn" {
  type = string
}

variable "table_arn" {
  type = string
}

variable "worker_function_arn" {
  type = string
}

variable "lambda_zip_path" {
  type = string
}

variable "lambda_zip_hash" {
  type = string
}

variable "common_env" {
  type = map(string)
}

variable "bedrock_model_id" {
  type = string
}

variable "bedrock_policy_json" {
  type = string
}

variable "transcribe_policy_json" {
  type = string
}

variable "transcribe_max_polls" {
  description = "5-second polls before TRANSCRIBE_TIMEOUT (system design: 40)."
  type        = number
  default     = 40
}

variable "log_retention_days" {
  type = number
}
