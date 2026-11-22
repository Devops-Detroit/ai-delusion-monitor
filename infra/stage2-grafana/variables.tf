variable "region" {
  type    = string
  default = "us-east-1"
}

variable "grafana_url" {
  description = "Grafana as the Terraform runner sees it: the local end of the SSM tunnel."
  type        = string
  default     = "http://localhost:3000"
}

variable "grafana_admin_password" {
  description = "Override for local testing. When null, the password is read from SSM Parameter Store."
  type        = string
  default     = null
  sensitive   = true
}

variable "grafana_admin_password_ssm_name" {
  description = "Matches the stage 1 output grafana_admin_password_ssm_name."
  type        = string
  default     = "/ai-delusion-monitor/grafana/admin-password"
}

variable "prometheus_url" {
  description = "Prometheus as Grafana sees it, inside the task's shared network namespace."
  type        = string
  default     = "http://localhost:9090"
}

variable "alert_webhook_url" {
  type    = string
  default = "http://localhost:8000/alerts"
}

variable "alert_window" {
  description = "Time window for both the flagged rate and the minimum evaluation count."
  type        = string
  default     = "15m"
}

variable "alert_min_evaluations" {
  description = "The alert cannot fire for a prompt version with fewer evaluations than this in the window."
  type        = number
  default     = 10
}

variable "alert_flagged_rate_threshold" {
  description = "Fire when the flagged-answer rate exceeds this fraction."
  type        = number
  default     = 0.3
}

variable "alert_pending_period" {
  type    = string
  default = "1m"
}
