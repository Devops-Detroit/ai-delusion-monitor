output "dashboard_url" {
  value = "${var.grafana_url}/d/${jsondecode(grafana_dashboard.this.config_json).uid}"
}

output "alert_rule_uid" {
  value = grafana_rule_group.this.rule[0].uid
}

output "datasource_uid" {
  value = grafana_data_source.prometheus.uid
}
