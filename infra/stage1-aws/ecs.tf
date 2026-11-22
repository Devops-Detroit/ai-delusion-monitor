resource "aws_cloudwatch_log_group" "this" {
  name              = local.log_group
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

locals {
  image_ref = { for k, img in data.aws_ecr_image.this : k => "${aws_ecr_repository.this[k].repository_url}@${img.image_digest}" }

  log_config = { for c in local.images : c => {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.this.name
      awslogs-region        = var.region
      awslogs-stream-prefix = c
    }
  } }

  # All three containers share the task's network namespace (awsvpc), so they
  # talk over localhost. Each one binds to 127.0.0.1 only.
  containers = [
    {
      name             = "evaluator"
      image            = lookup(local.image_ref, "evaluator", null)
      essential        = true
      command          = ["serve", "--host", "127.0.0.1", "--port", "8000"]
      portMappings     = [{ containerPort = 8000, protocol = "tcp" }]
      logConfiguration = local.log_config["evaluator"]
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
    },
    {
      name             = "prometheus"
      image            = lookup(local.image_ref, "prometheus", null)
      essential        = true
      portMappings     = [{ containerPort = 9090, protocol = "tcp" }]
      logConfiguration = local.log_config["prometheus"]
      dependsOn        = [{ containerName = "evaluator", condition = "HEALTHY" }]
    },
    {
      name             = "grafana"
      image            = lookup(local.image_ref, "grafana", null)
      essential        = true
      portMappings     = [{ containerPort = 3000, protocol = "tcp" }]
      logConfiguration = local.log_config["grafana"]
      dependsOn        = [{ containerName = "prometheus", condition = "START" }]
      environment = [
        { name = "GF_SERVER_HTTP_ADDR", value = "127.0.0.1" },
        { name = "GF_SERVER_HTTP_PORT", value = "3000" },
        { name = "GF_USERS_ALLOW_SIGN_UP", value = "false" },
        { name = "GF_AUTH_ANONYMOUS_ENABLED", value = "false" },
        { name = "GF_ANALYTICS_REPORTING_ENABLED", value = "false" },
        { name = "GF_ANALYTICS_CHECK_FOR_UPDATES", value = "false" },
      ]
      secrets = [
        { name = "GF_SECURITY_ADMIN_PASSWORD", valueFrom = aws_ssm_parameter.grafana_admin_password.arn },
      ]
    },
  ]
}

resource "aws_ecs_task_definition" "this" {
  count                    = var.create_service ? 1 : 0
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode(local.containers)

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  # V1 storage is the task's ephemeral storage (default 20 GiB). Prometheus TSDB
  # and the Grafana SQLite database reset whenever the task is replaced.
}

resource "aws_ecs_service" "this" {
  count                  = var.create_service ? 1 : 0
  name                   = var.name
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.this[0].arn
  desired_count          = 1
  launch_type            = "FARGATE"
  platform_version       = "LATEST"
  enable_execute_command = true # needed for the SSM tunnel to Grafana and for ECS Exec

  # Stop the old task before starting the new one, so only one task runs at a time.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true # outbound only: no inbound rules, no load balancer
  }

  wait_for_steady_state = true
}
