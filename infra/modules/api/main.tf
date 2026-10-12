# Public HTTP API and its Lambda (system design §3).

locals {
  fn_name = "${var.name_prefix}-api"
}

# Created before the function so AWS never auto-creates an unmanaged log
# group that would survive `terraform destroy` (§8.1 rule 4).
resource "aws_cloudwatch_log_group" "api_fn" {
  name              = "/aws/lambda/${local.fn_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.name_prefix}-http-api"
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

resource "aws_iam_role" "api" {
  name               = "${local.fn_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

# Least privilege (§11): sign upload URLs for uploads/* only, read-sign
# results, uploads and references, check that an upload arrived, and touch
# only this table and this state machine.
data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api_fn.arn}:*"]
  }

  statement {
    sid       = "SignUploads"
    actions   = ["s3:PutObject"]
    resources = ["${var.bucket_arn}/uploads/*"]
  }

  statement {
    sid     = "SignReads"
    actions = ["s3:GetObject"]
    resources = [
      "${var.bucket_arn}/results/*",
      "${var.bucket_arn}/uploads/*",
      "${var.bucket_arn}/references/*",
    ]
  }

  # Without ListBucket, HeadObject on a missing key returns 403 instead of
  # 404; scoped to the uploads/ prefix.
  statement {
    sid       = "HeadUploads"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["uploads/*"]
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

  statement {
    sid       = "StartAnalysis"
    actions   = ["states:StartExecution"]
    resources = [var.state_machine_arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${local.fn_name}-policy"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  function_name    = local.fn_name
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "speakquest_api.lambdas.api_handler"
  filename         = var.lambda_zip_path
  source_code_hash = var.lambda_zip_hash
  memory_size      = 512
  timeout          = 10

  environment {
    variables = merge(var.common_env, {
      SPEAKQUEST_STATE_MACHINE_ARN = var.state_machine_arn
    })
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.api_fn.name
  }

  depends_on = [aws_cloudwatch_log_group.api_fn, aws_iam_role_policy.api]
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name_prefix}-http-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = var.allowed_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["content-type", "x-session-id"]
    max_age       = 600
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "routes" {
  for_each = toset([
    "GET /challenges",
    "POST /uploads",
    "POST /analyses",
    "GET /analyses/{id}",
    "GET /analyses/{id}/result",
    "GET /me/progress",
  ])
  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  # Abuse limits (§3): 10 rps steady, burst 20.
  default_route_settings {
    throttling_rate_limit  = var.throttle_rate
    throttling_burst_limit = var.throttle_burst
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      ip        = "$context.identity.sourceIp"
      route     = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
      error     = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
