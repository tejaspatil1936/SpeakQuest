# Step Functions Standard workflow plus the two zip Lambdas it owns
# (Explain → Bedrock, Persist/MarkFailed → S3 + DynamoDB). See
# definition.asl.json for the states.

locals {
  explain_name = "${var.name_prefix}-explain"
  persist_name = "${var.name_prefix}-persist"
  sm_name      = "${var.name_prefix}-analysis"
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

# ---------------------------------------------------------------- explain

resource "aws_cloudwatch_log_group" "explain" {
  name              = "/aws/lambda/${local.explain_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "explain" {
  name               = "${local.explain_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "explain" {
  source_policy_documents = [var.bedrock_policy_json]

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.explain.arn}:*"]
  }

  statement {
    sid       = "Results"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${var.bucket_arn}/results/*"]
  }

  statement {
    sid       = "Stage"
    actions   = ["dynamodb:UpdateItem"]
    resources = [var.table_arn]
  }
}

resource "aws_iam_role_policy" "explain" {
  name   = "${local.explain_name}-policy"
  role   = aws_iam_role.explain.id
  policy = data.aws_iam_policy_document.explain.json
}

resource "aws_lambda_function" "explain" {
  function_name    = local.explain_name
  role             = aws_iam_role.explain.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "speakquest_api.lambdas.explain_handler"
  filename         = var.lambda_zip_path
  source_code_hash = var.lambda_zip_hash
  memory_size      = 256
  timeout          = 60

  environment {
    variables = merge(var.common_env, {
      SPEAKQUEST_BEDROCK_MODEL_ID = var.bedrock_model_id
    })
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.explain.name
  }

  depends_on = [aws_cloudwatch_log_group.explain, aws_iam_role_policy.explain]
}

# ---------------------------------------------------------------- persist

resource "aws_cloudwatch_log_group" "persist" {
  name              = "/aws/lambda/${local.persist_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "persist" {
  name               = "${local.persist_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "persist" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.persist.arn}:*"]
  }

  statement {
    sid       = "Results"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${var.bucket_arn}/results/*"]
  }

  # A missing coaching.json must read as 404 (template fallback), not 403.
  statement {
    sid       = "ListResults"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["results/*"]
    }
  }

  statement {
    sid = "Table"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
    ]
    resources = [var.table_arn]
  }
}

resource "aws_iam_role_policy" "persist" {
  name   = "${local.persist_name}-policy"
  role   = aws_iam_role.persist.id
  policy = data.aws_iam_policy_document.persist.json
}

resource "aws_lambda_function" "persist" {
  function_name    = local.persist_name
  role             = aws_iam_role.persist.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "speakquest_api.lambdas.persist_handler"
  filename         = var.lambda_zip_path
  source_code_hash = var.lambda_zip_hash
  memory_size      = 256
  timeout          = 30

  environment {
    variables = var.common_env
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.persist.name
  }

  depends_on = [aws_cloudwatch_log_group.persist, aws_iam_role_policy.persist]
}

# ---------------------------------------------------------------- state machine

resource "aws_cloudwatch_log_group" "states" {
  name              = "/aws/vendedlogs/states/${local.sm_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume_states" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "states" {
  name               = "${local.sm_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_states.json
}

data "aws_iam_policy_document" "states" {
  source_policy_documents = [var.transcribe_policy_json]

  statement {
    sid     = "InvokeSteps"
    actions = ["lambda:InvokeFunction"]
    resources = [
      var.worker_function_arn,
      "${var.worker_function_arn}:*",
      aws_lambda_function.explain.arn,
      aws_lambda_function.persist.arn,
    ]
  }

  # Step Functions log delivery uses account-level CloudWatch Logs APIs that
  # do not support resource-level permissions.
  statement {
    sid = "LogDelivery"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "states" {
  name   = "${local.sm_name}-policy"
  role   = aws_iam_role.states.id
  policy = data.aws_iam_policy_document.states.json
}

resource "aws_sfn_state_machine" "analysis" {
  name     = local.sm_name
  role_arn = aws_iam_role.states.arn
  type     = "STANDARD"
  definition = templatefile("${path.module}/definition.asl.json", {
    worker_arn  = var.worker_function_arn
    explain_arn = aws_lambda_function.explain.arn
    persist_arn = aws_lambda_function.persist.arn
    bucket      = var.bucket_name
    name_prefix = var.name_prefix
    max_polls   = var.transcribe_max_polls
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.states.arn}:*"
    include_execution_data = false # recordings' metadata stays out of logs
    level                  = "ERROR"
  }

  depends_on = [aws_iam_role_policy.states]
}
