#!/usr/bin/env bash
# Open an SSM port-forwarding session from this machine into the running ECS task.
#   scripts/tunnel.sh grafana     -> http://localhost:3000   (browser and stage 2 Terraform)
#   scripts/tunnel.sh prometheus  -> http://localhost:9090
#   scripts/tunnel.sh evaluator   -> http://localhost:8000   (replay batches with --target)
# Prerequisites: AWS CLI v2, session-manager-plugin, IAM permission for
# ecs:ListTasks, ecs:DescribeTasks, and ssm:StartSession on the task. The
# service must run with enable_execute_command=true (stage 1 sets this).
# Keep the session open in its own terminal. Ctrl-C closes it.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-grafana}" in
  grafana) PORT=3000 ;; prometheus) PORT=9090 ;; evaluator) PORT=8000 ;;
  *) echo "usage: $0 grafana|prometheus|evaluator [local_port]" >&2; exit 2 ;;
esac
LOCAL_PORT="${2:-$PORT}"
TF="terraform -chdir=infra/stage1-aws"
# These come from stage 1 outputs unless you export them (needed for a stack built by hand).
REGION="${REGION:-$($TF output -raw region)}"
CLUSTER="${CLUSTER:-$($TF output -raw cluster_name)}"
SERVICE="${SERVICE:-$($TF output -raw service_name)}"

TASK_ARN=$(aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --service-name "$SERVICE" \
  --desired-status RUNNING --query 'taskArns[0]' --output text)
[ "$TASK_ARN" != "None" ] || { echo "no running task for service $SERVICE" >&2; exit 1; }
TASK_ID="${TASK_ARN##*/}"
# Any container's runtime ID works because all containers share one network namespace.
RUNTIME_ID=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query "tasks[0].containers[?name=='evaluator'].runtimeId | [0]" --output text)

echo "Forwarding localhost:$LOCAL_PORT -> task $TASK_ID 127.0.0.1:$PORT"
exec aws ssm start-session --region "$REGION" \
  --target "ecs:${CLUSTER}_${TASK_ID}_${RUNTIME_ID}" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"$PORT\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}"
# Note: AWS-StartPortForwardingSessionToRemoteHost (host=127.0.0.1) accepted
# connections but passed no data to this ECS target (verified 2026-11-22), so
# this script uses the plain document. It reaches the task's localhost directly.
