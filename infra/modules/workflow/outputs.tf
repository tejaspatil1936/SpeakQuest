output "state_machine_arn" {
  value = aws_sfn_state_machine.analysis.arn
}

output "state_machine_name" {
  value = aws_sfn_state_machine.analysis.name
}

output "explain_function_name" {
  value = aws_lambda_function.explain.function_name
}

output "persist_function_name" {
  value = aws_lambda_function.persist.function_name
}
