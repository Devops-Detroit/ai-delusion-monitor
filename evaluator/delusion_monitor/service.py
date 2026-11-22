"""Evaluation service: runs checks, writes structured logs, and updates Prometheus counters."""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge

from . import checker
from .data import Case, allowed_prompt_versions, load_cases

log = logging.getLogger("delusion_monitor")

REJECT_REASONS = ("unknown_case", "unknown_prompt_version", "bad_request")
ALERT_STATUSES = ("firing", "resolved", "other")
MAX_RESPONSE_CHARS = 4000


class EvaluationError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def log_event(event: str, **fields) -> None:
    """Write one JSON object per line. CloudWatch Logs can filter these with `{ $.verdict = ... }`."""
    log.info(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}))


@dataclass
class Metrics:
    registry: CollectorRegistry
    evaluations: Counter
    rejected: Counter
    alert_notifications: Counter
    info: Gauge

    @classmethod
    def create(cls, prompt_versions: tuple[str, ...], registry: CollectorRegistry | None = None) -> "Metrics":
        registry = registry if registry is not None else CollectorRegistry()
        evaluations = Counter(
            "delusion_evaluations", "Evaluated responses by verdict and prompt version.",
            ["verdict", "prompt_version"], registry=registry,
        )
        rejected = Counter("delusion_rejected_requests", "Requests rejected before evaluation.", ["reason"], registry=registry)
        alerts = Counter("delusion_alert_notifications", "Grafana alert webhook notifications received.", ["status"], registry=registry)
        info = Gauge("delusion_evaluator_info", "Static evaluator information.", ["version"], registry=registry)
        # Create every label combination at zero, so increase() also counts the
        # first evaluation after the process starts.
        for v in checker.VERDICTS:
            for pv in prompt_versions:
                evaluations.labels(verdict=v, prompt_version=pv)
        for r in REJECT_REASONS:
            rejected.labels(reason=r)
        for s in ALERT_STATUSES:
            alerts.labels(status=s)
        from . import __version__
        info.labels(version=__version__).set(1)
        return cls(registry, evaluations, rejected, alerts, info)


class EvaluatorService:
    def __init__(self, metrics: Metrics | None = None):
        self.cases, self.facts = load_cases()
        self.prompt_versions = allowed_prompt_versions()
        self.metrics = metrics or Metrics.create(self.prompt_versions)

    def evaluate(self, case_id: str, response: str | None = None, prompt_version: str | None = None) -> dict:
        case: Case | None = self.cases.get(case_id)
        if case is None:
            raise EvaluationError("unknown_case", f"unknown case_id {case_id!r}; known: {sorted(self.cases)}")
        pv = prompt_version or self.prompt_versions[0]
        if pv not in self.prompt_versions:
            raise EvaluationError("unknown_prompt_version", f"prompt_version {pv!r} not in {list(self.prompt_versions)}")
        text = case.canned_response if response is None else response
        if not isinstance(text, str) or len(text) > MAX_RESPONSE_CHARS:
            raise EvaluationError("bad_request", f"response must be a string of at most {MAX_RESPONSE_CHARS} characters")

        result = checker.check(text, case.environment, self.facts)
        self.metrics.evaluations.labels(verdict=result.verdict, prompt_version=pv).inc()
        record = {
            "case_id": case.id,
            "category": case.category,
            "prompt_version": pv,
            "question": case.question,
            "response": text,
            "verdict": result.verdict,
            "reason": result.reason,
            "expected_verdict": case.expected_verdict if response is None else None,
        }
        log_event("evaluation", **record)
        return record

    def record_alert(self, payload: dict) -> dict:
        status = payload.get("status") if payload.get("status") in ("firing", "resolved") else "other"
        self.metrics.alert_notifications.labels(status=status).inc()
        alerts = payload.get("alerts") or []
        summary = {
            "status": status,
            "alert_count": len(alerts),
            "alerts": [
                {"name": a.get("labels", {}).get("alertname"), "prompt_version": a.get("labels", {}).get("prompt_version"), "status": a.get("status")}
                for a in alerts[:20]
            ],
        }
        log_event("alert_notification", **summary)
        return summary
