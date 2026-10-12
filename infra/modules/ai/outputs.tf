output "bedrock_policy_json" {
  value = data.aws_iam_policy_document.bedrock_invoke.json
}

output "transcribe_policy_json" {
  value = data.aws_iam_policy_document.transcribe.json
}
