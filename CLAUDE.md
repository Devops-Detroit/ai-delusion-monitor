# AI Delusion Monitor: project instructions

**Goal:** portfolio project. Grafana tracks when an AI assistant contradicts its source (a fictional EKS logging runbook) or makes claims the source doesn't support. Verdicts: `pass`, `contradicted`, `unsupported`. Full details are in README.md.

## Architecture (V1)
- One ECS Fargate task (service desired count 1) with three containers sharing localhost (awsvpc):
  - `evaluator`: Python, :8000, `/evaluate`, `/metrics`, `/alerts`
  - `prometheus`: :9090, scrapes `localhost:8000`
  - `grafana`: :3000, queries `localhost:9090`
- All three containers bind to 127.0.0.1.
- Storage is ephemeral: Prometheus TSDB, counters, and the Grafana DB reset when the task is replaced. Restore Grafana by re-applying stage 2.

## Terraform: two stages, separate state
- `infra/stage1-aws`: VPC, ECR, IAM, CloudWatch Logs, cluster, task definition, service. Bootstrap order:
  1. `apply` (create_service=false)
  2. `scripts/push-images.sh`
  3. `apply -var create_service=true`. The plan fails if any image is missing, and images are pinned by digest.
- `infra/stage2-grafana`: data source, folder, dashboard, contact point, alert rule. The runner reaches Grafana at `localhost:3000` through `scripts/tunnel.sh grafana`. The password is read from SSM.

## Private Grafana
- No load balancer, no security group ingress. Access is SSM port forwarding only (`scripts/tunnel.sh grafana|prometheus|evaluator`).
- Requires session-manager-plugin and ECS Exec (enabled on the service).

## Demo: canned answers, no LLM or API key
- Six cases in `data/cases.json`. Facts are parsed from `data/runbook/eks-logging-runbook.md`.
- Headline case: `prod-retention` with response "365 days." gives `contradicted` (the runbook says 90 days).
- `data/batches/alert-demo.json` (12 evaluations, 75% flagged, `canned-v2`) crosses the alert gates (≥10 evaluations and >30% in 15m). The six canned cases alone must not cross them.
- Keep metric labels bounded. `prompt_version` is allowlisted in `evaluator/delusion_monitor/data.py`. Questions and responses go in logs, never in labels.

## Verification
```bash
make venv && make check      # pytest + terraform fmt/validate (both stages) + bash -n; offline
make local-up                # 3 containers in one netns, the same topology as the task
make local-grafana           # stage 2 against LOCAL Grafana (state in .local-state/)
make demo-case               # exits 1 unless "365 days." -> contradicted
make replay                  # 6 canned cases; alert must stay Normal
make replay-alert            # alert must reach Firing; evaluator logs event=alert_notification
make local-down
```

## Rules
- **Never `terraform apply` or `destroy` against AWS, or push to ECR, without the user's explicit approval in the current conversation.** `validate`, `fmt`, and local-only stage 2 runs are fine.
- When you change cases or the batch, keep `expected_verdict` correct. `make test` enforces it.
- Real LLM integration is the follow-up milestone, in the planning stage only: see `docs/LLM_INTEGRATION.md`. The model and runbook stay fixed, and `prompt-a` is compared with `prompt-b`.
