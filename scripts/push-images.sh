#!/usr/bin/env bash
# Build the evaluator and Prometheus images, mirror the pinned Grafana image,
# and push all three to the ECR repositories that stage 1 created.
# Run this after the first stage 1 apply (create_service=false) and before the
# apply with create_service=true.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${IMAGE_TAG:-v1}"
GRAFANA_UPSTREAM="${GRAFANA_UPSTREAM:-grafana/grafana:12.2.0}"
TF="terraform -chdir=infra/stage1-aws"

# REGION and REGISTRY come from stage 1 outputs. Export them yourself to skip
# Terraform, for example on a stack built by hand (docs/MANUAL_SETUP.md).
REGION="${REGION:-$($TF output -raw region)}"
REGISTRY="${REGISTRY:-$($TF output -raw ecr_registry)}"
NAME="${NAME:-ai-delusion-monitor}"
repo() { echo "$REGISTRY/$NAME/$1"; }

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

docker build --platform linux/amd64 -t "$(repo evaluator):$TAG" -f evaluator/Dockerfile .
docker build --platform linux/amd64 -t "$(repo prometheus):$TAG" prometheus
docker pull --platform linux/amd64 "$GRAFANA_UPSTREAM"
docker tag "$GRAFANA_UPSTREAM" "$(repo grafana):$TAG"

for r in evaluator prometheus grafana; do
  docker push "$(repo $r):$TAG"
done
echo "Pushed tag $TAG. Next: terraform -chdir=infra/stage1-aws apply -var create_service=true (or register the task definition by hand)"
