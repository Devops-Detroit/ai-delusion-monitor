#!/usr/bin/env bash
docker rm -f adm-grafana adm-prometheus adm-evaluator >/dev/null 2>&1 || true
