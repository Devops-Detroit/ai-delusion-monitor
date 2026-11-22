# Runbook: EKS Control Plane Logging

> **Fictional document.** Written for the AI Delusion Monitor demo. It does not
> describe any real organization's systems or policies.

- **Owner:** Platform Engineering (Cluster Operations)
- **Last reviewed:** 2026-10-01
- **Applies to:** `eks-prod-use1`, `eks-dev-use1`, `eks-test-use1`

## Purpose

This runbook explains how EKS control plane logs are collected and how long
audit logs are kept. On-call engineers use it to answer audit and
incident-response questions.

## Log types enabled

Every cluster ships the following control plane log types to CloudWatch Logs:

- `api`
- `audit`
- `authenticator`

The `controllerManager` and `scheduler` log types are disabled by default to
reduce cost. You can enable them for up to 24 hours while debugging.

## Where logs are stored

Control plane logs go to the log group `/aws/eks/<cluster-name>/cluster`
in the cluster's own AWS account. The test cluster (`eks-test-use1`) ships
`api`, `audit`, and `authenticator` logs the same way as the other clusters.

## Audit log retention

| Environment | Cluster         | Audit log retention |
|-------------|-----------------|---------------------|
| Production  | `eks-prod-use1` | 90 days             |
| Dev         | `eks-dev-use1`  | 14 days             |

The retention period is set on the CloudWatch log group. After the retention
period ends, CloudWatch deletes the events automatically. Do not change the
retention setting without a change request approved by Security.

## Requesting older logs

CloudWatch cannot recover events after the retention period ends. If an
investigation needs logs that are older than the retention period, escalate to
Security. Do not open a CloudWatch support ticket.

## Troubleshooting

1. **No audit events in the log group:** Confirm that `audit` is in the
   cluster's enabled log types. Run
   `aws eks describe-cluster --name <cluster> --query cluster.logging`.
2. **Gaps in the logs:** Check the AWS Health Dashboard for EKS control plane
   incidents in the region.
