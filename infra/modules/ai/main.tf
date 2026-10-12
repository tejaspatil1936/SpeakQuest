# IAM policy documents for the two managed AI services. They are attached by
# the modules that own the roles (explain Lambda, state machine).

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  # A cross-region inference profile id ("us.amazon.nova-2-lite-v1:0") routes
  # to the foundation model in several US regions, so both the profile and
  # the underlying model ARNs must be allowed.
  is_profile = can(regex("^(us|eu|apac|global)\\.", var.bedrock_model_id))
  base_model = local.is_profile ? replace(var.bedrock_model_id, "/^(us|eu|apac|global)\\./", "") : var.bedrock_model_id
  bedrock_arns = concat(
    local.is_profile ? [
      "arn:${data.aws_partition.current.partition}:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}",
    ] : [],
    ["arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/${local.base_model}"],
  )
}

data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid       = "InvokeCoachingModel"
    actions   = ["bedrock:InvokeModel"]
    resources = local.bedrock_arns
  }
}

# StartTranscriptionJob runs with the caller's permissions, so the state
# machine role also needs to read the normalised audio and write the output.
data "aws_iam_policy_document" "transcribe" {
  statement {
    sid = "TranscriptionJobs"
    actions = [
      "transcribe:StartTranscriptionJob",
      "transcribe:GetTranscriptionJob",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:transcribe:${var.region}:${data.aws_caller_identity.current.account_id}:transcription-job/${var.name_prefix}-*",
    ]
  }

  statement {
    sid       = "ReadNormalisedAudio"
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/work/*"]
  }

  statement {
    sid       = "WriteTranscripts"
    actions   = ["s3:PutObject"]
    resources = ["${var.bucket_arn}/transcripts/*"]
  }
}
