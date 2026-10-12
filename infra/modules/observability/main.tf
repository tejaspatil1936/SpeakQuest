# Spend alerts and failure alarms. Budgets alert; they never cap spending
# (system design §8.6). The budget lives in Terraform so destroy removes it.

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Account-wide on purpose: a project-tag filter needs the cost-allocation
  # tag activated in Billing first (up to 24 h), and an inactive filter would
  # silently report $0. Erring towards more alerts is the safe default.

  dynamic "notification" {
    for_each = var.alert_thresholds_usd
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "workflow_failures" {
  alarm_name          = "${var.name_prefix}-analysis-failures"
  alarm_description   = "Analyses ending in FAILED. Many are user audio problems; a burst means a regression."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = var.state_machine_arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name_prefix}-api-5xx"
  alarm_description   = "Server errors from the HTTP API."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = var.api_id, Stage = "$default" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
