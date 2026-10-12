variable "name_prefix" {
  type = string
}

variable "alert_email" {
  type = string
}

variable "limit_usd" {
  type = number
}

variable "alert_thresholds_usd" {
  type = list(number)
}

variable "state_machine_arn" {
  type = string
}

variable "api_id" {
  type = string
}
