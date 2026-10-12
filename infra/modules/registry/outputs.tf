output "repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

output "repository_arn" {
  value = aws_ecr_repository.worker.arn
}

output "repository_name" {
  value = aws_ecr_repository.worker.name
}
