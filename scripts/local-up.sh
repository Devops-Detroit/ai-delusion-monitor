#!/usr/bin/env bash
# Run the three containers locally the way the ECS task runs them: one shared
# network namespace, so Prometheus and Grafana talk over localhost.
# Grafana is published on 127.0.0.1:3000 and the evaluator on 127.0.0.1:8000.
set -euo pipefail
cd "$(dirname "$0")/.."
GRAFANA_IMAGE="${GRAFANA_IMAGE:-grafana/grafana:12.2.0}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-local-admin}"

docker build -q -t adm-evaluator:local -f evaluator/Dockerfile . >/dev/null
docker build -q -t adm-prometheus:local prometheus >/dev/null
"$(dirname "$0")/local-down.sh" 2>/dev/null || true

docker run -d --name adm-evaluator -p 127.0.0.1:8000:8000 -p 127.0.0.1:3000:3000 -p 127.0.0.1:9090:9090 adm-evaluator:local >/dev/null
docker run -d --name adm-prometheus --network container:adm-evaluator adm-prometheus:local \
  --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --web.listen-address=0.0.0.0:9090 >/dev/null
docker run -d --name adm-grafana --network container:adm-evaluator \
  -e GF_SECURITY_ADMIN_PASSWORD="$GRAFANA_ADMIN_PASSWORD" -e GF_USERS_ALLOW_SIGN_UP=false \
  -e GF_ANALYTICS_REPORTING_ENABLED=false -e GF_ANALYTICS_CHECK_FOR_UPDATES=false \
  "$GRAFANA_IMAGE" >/dev/null

for i in $(seq 1 60); do
  curl -fs http://127.0.0.1:3000/api/health >/dev/null 2>&1 && curl -fs http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break
  sleep 2
done
echo "evaluator  http://127.0.0.1:8000   prometheus http://127.0.0.1:9090   grafana http://127.0.0.1:3000 (admin / $GRAFANA_ADMIN_PASSWORD)"
