variable "name_prefix" {
  type = string
}

variable "repository_url" {
  type = string
}

variable "image_tag" {
  type = string
}

variable "image_digest" {
  type = string
}

variable "bucket_arn" {
  type = string
}

variable "table_arn" {
  type = string
}

variable "common_env" {
  type = map(string)
}

variable "log_retention_days" {
  type = number
}
