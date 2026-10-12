output "budget_name" {
  value = aws_budgets_budget.monthly.name
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
