# Analysis worker: a Lambda container image (system design §4, "Worker
# runtime"). Python 3.12 + numpy/scipy/parselmouth + a static ffmpeg; no
# PyTorch, no VPC, no idle cost. One function serves the Normalize and
# Analyze states (the state passes {"step": ...}).

locals {
  fn_name   = "${var.name_prefix}-worker"
  image_ref = var.image_digest != "" ? "${var.repository_url}@${var.image_digest}" : "${var.repository_url}:${var.image_tag}"
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.fn_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.fn_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.worker.arn}:*"]
  }

  statement {
    sid     = "ReadInputs"
    actions = ["s3:GetObject"]
    resources = [
      "${var.bucket_arn}/uploads/*",
      "${var.bucket_arn}/work/*",
      "${var.bucket_arn}/transcripts/*",
      "${var.bucket_arn}/references/*",
    ]
  }

  # Missing objects should read as 404, not 403.
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["uploads/*", "work/*", "transcripts/*", "references/*"]
    }
  }

  statement {
    sid     = "WriteOutputs"
    actions = ["s3:PutObject"]
    resources = [
      "${var.bucket_arn}/work/*",
      "${var.bucket_arn}/results/*",
    ]
  }

  statement {
    sid       = "Table"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [var.table_arn]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "${local.fn_name}-policy"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_lambda_function" "worker" {
  function_name = local.fn_name
  role          = aws_iam_role.worker.arn
  package_type  = "Image"
  image_uri     = local.image_ref
  architectures = ["x86_64"]
  memory_size   = 3008
  timeout       = 300

  ephemeral_storage {
    size = 2048
  }

  environment {
    variables = merge(var.common_env, {
      SPEAKQUEST_IMAGE_DIGEST = var.image_digest != "" ? var.image_digest : "tag:${var.image_tag}"
    })
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.worker.name
  }

  depends_on = [aws_cloudwatch_log_group.worker, aws_iam_role_policy.worker]
}
