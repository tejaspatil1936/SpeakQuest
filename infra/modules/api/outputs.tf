output "api_id" {
  value = aws_apigatewayv2_api.http.id
}

output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "function_name" {
  value = aws_lambda_function.api.function_name
}
