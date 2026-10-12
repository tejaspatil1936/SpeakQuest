variable "name_prefix" {
  description = "speakquest-<env>"
  type        = string
}

variable "allowed_origins" {
  description = "Browser origins allowed to PUT/GET presigned URLs."
  type        = list(string)
}
