variable "name_prefix" {
  type = string
}

variable "bucket_arn" {
  type = string
}

variable "table_arn" {
  type = string
}

variable "state_machine_arn" {
  type = string
}

variable "lambda_zip_path" {
  type = string
}

variable "lambda_zip_hash" {
  type = string
}

variable "common_env" {
  description = "Environment shared by every SpeakQuest function."
  type        = map(string)
}

variable "allowed_origins" {
  type = list(string)
}

variable "throttle_rate" {
  type = number
}

variable "throttle_burst" {
  type = number
}

variable "log_retention_days" {
  type = number
}
