output "region" {
  value = var.region
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "ecr_registry" {
  value = split("/", aws_ecr_repository.this["evaluator"].repository_url)[0]
}

output "ecr_repositories" {
  value = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = var.create_service ? aws_ecs_service.this[0].name : null
}

output "log_group" {
  value = aws_cloudwatch_log_group.this.name
}

output "grafana_admin_password_ssm_name" {
  description = "Stage 2 reads this SecureString to authenticate to Grafana."
  value       = aws_ssm_parameter.grafana_admin_password.name
}

output "image_digests" {
  value = local.image_ref
}
