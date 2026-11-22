variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "ai-delusion-monitor"
}

variable "create_service" {
  description = <<-EOT
    Bootstrap gate. Keep this false for the first apply, which creates ECR, IAM,
    networking, logs, and the cluster. Push the images, then apply with true to
    create the task definition and the service. When true, Terraform looks up
    each image in ECR and fails the plan if any image is missing.
  EOT
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Tag pushed by scripts/push-images.sh. The task definition pins each image by digest."
  type        = string
  default     = "v1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "log_retention_days" {
  type    = number
  default = 14
}
