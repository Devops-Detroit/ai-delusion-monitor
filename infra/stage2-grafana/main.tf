terraform {
  required_version = ">= 1.6"
  required_providers {
    grafana = {
      source  = "grafana/grafana"
      version = "~> 4.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Grafana is private. The Terraform runner reaches it through an SSM
# port-forwarding session (scripts/tunnel.sh grafana), which exposes the
# task's 127.0.0.1:3000 on the runner's localhost:3000.
provider "aws" {
  region = var.region
}

data "aws_ssm_parameter" "grafana_admin_password" {
  count           = var.grafana_admin_password == null ? 1 : 0
  name            = var.grafana_admin_password_ssm_name
  with_decryption = true
}

provider "grafana" {
  url  = var.grafana_url
  auth = "admin:${coalesce(var.grafana_admin_password, try(data.aws_ssm_parameter.grafana_admin_password[0].value, null))}"
}

locals {
  # PromQL shared by the dashboard and the alert rule.
  # Flagged-answer rate = (contradicted + unsupported) / all evaluations, both in the same window.
  flagged_rate_expr = "sum by (prompt_version) (increase(delusion_evaluations_total{verdict=~\"contradicted|unsupported\"}[%s])) / sum by (prompt_version) (increase(delusion_evaluations_total[%s]))"
  total_expr        = "sum by (prompt_version) (increase(delusion_evaluations_total[%s]))"
}

resource "grafana_data_source" "prometheus" {
  type       = "prometheus"
  name       = "Prometheus"
  uid        = "adm-prometheus"
  url        = var.prometheus_url
  is_default = true
  json_data_encoded = jsonencode({
    httpMethod   = "POST"
    timeInterval = "15s"
  })
}

resource "grafana_folder" "this" {
  title = "AI Delusion Monitor"
  uid   = "ai-delusion-monitor"
}

resource "grafana_dashboard" "this" {
  folder    = grafana_folder.this.uid
  overwrite = true
  config_json = templatefile("${path.module}/dashboards/delusion-monitor.json.tftpl", {
    ds_uid = grafana_data_source.prometheus.uid
    # ">= 0" drops NaN (0/0) series for prompt versions with no evaluations in the window.
    flagged_rate   = jsonencode("(${format(local.flagged_rate_expr, var.alert_window, var.alert_window)}) >= 0")
    rate_threshold = var.alert_flagged_rate_threshold
    window         = var.alert_window
    min_count      = var.alert_min_evaluations
  })
}

# Notifications go to the evaluator's /alerts endpoint over localhost inside
# the task. The evaluator logs each notification and counts it.
resource "grafana_contact_point" "evaluator_webhook" {
  name = "evaluator-webhook"
  webhook {
    url                     = var.alert_webhook_url
    disable_resolve_message = false
  }
}

resource "grafana_rule_group" "this" {
  name             = "grounding"
  folder_uid       = grafana_folder.this.uid
  interval_seconds = 60

  rule {
    name      = "High flagged-answer rate"
    condition = "C"
    for       = var.alert_pending_period
    # When fewer than min_count evaluations exist in the window, query A returns
    # no series. NoData = OK, so the alert cannot fire on small samples.
    no_data_state  = "OK"
    exec_err_state = "Error"

    labels = { severity = "warning", project = "ai-delusion-monitor" }
    annotations = {
      summary     = "Flagged-answer rate for {{ $labels.prompt_version }} is {{ humanizePercentage $values.B.Value }} over ${var.alert_window}"
      description = "More than ${var.alert_flagged_rate_threshold * 100}% of at least ${var.alert_min_evaluations} evaluated responses were contradicted or unsupported."
    }

    notification_settings {
      contact_point = grafana_contact_point.evaluator_webhook.name
      group_wait    = "10s"
    }

    data {
      ref_id         = "A"
      datasource_uid = grafana_data_source.prometheus.uid
      relative_time_range {
        from = 900
        to   = 0
      }
      model = jsonencode({
        refId   = "A"
        instant = true
        # The rate, kept only for prompt versions with at least min_count evaluations in the window.
        expr = "(${format(local.flagged_rate_expr, var.alert_window, var.alert_window)}) and on (prompt_version) (${format(local.total_expr, var.alert_window)} >= ${var.alert_min_evaluations})"
      })
    }

    data {
      ref_id         = "B"
      datasource_uid = "__expr__"
      relative_time_range {
        from = 0
        to   = 0
      }
      model = jsonencode({ refId = "B", type = "reduce", expression = "A", reducer = "last" })
    }

    data {
      ref_id         = "C"
      datasource_uid = "__expr__"
      relative_time_range {
        from = 0
        to   = 0
      }
      model = jsonencode({
        refId      = "C"
        type       = "threshold"
        expression = "B"
        conditions = [{ evaluator = { type = "gt", params = [var.alert_flagged_rate_threshold] } }]
      })
    }
  }
}
