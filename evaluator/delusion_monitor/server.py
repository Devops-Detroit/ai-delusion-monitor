"""HTTP server (standard library only).

  GET  /healthz   Liveness check.
  GET  /metrics   Prometheus metrics.
  GET  /cases     Test case definitions.
  POST /evaluate  {"case_id": ..., "response": ..., "prompt_version": ...}
                  If "response" is omitted, the case's canned response is used.
  POST /alerts    Receives Grafana webhook notifications and logs them.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .service import EvaluationError, EvaluatorService, log_event

MAX_BODY_BYTES = 64 * 1024


def make_handler(service: EvaluatorService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "delusion-monitor/1"

        def log_message(self, *args):  # access logs are noisy; evaluations are logged as JSON
            pass

        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj).encode())

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise EvaluationError("bad_request", "body must be JSON of 1..65536 bytes")
            try:
                obj = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as e:
                raise EvaluationError("bad_request", f"invalid JSON: {e}") from e
            if not isinstance(obj, dict):
                raise EvaluationError("bad_request", "body must be a JSON object")
            return obj

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, {"status": "ok"})
            elif path == "/metrics":
                self._send(200, generate_latest(service.metrics.registry), CONTENT_TYPE_LATEST)
            elif path == "/cases":
                self._json(200, {"facts": service.facts, "cases": [asdict(c) for c in service.cases.values()]})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                if path == "/evaluate":
                    body = self._read_json()
                    self._json(200, service.evaluate(body.get("case_id"), body.get("response"), body.get("prompt_version")))
                elif path == "/alerts":
                    self._json(200, service.record_alert(self._read_json()))
                else:
                    self._json(404, {"error": "not found"})
            except EvaluationError as e:
                service.metrics.rejected.labels(reason=e.reason).inc()
                self._json(400, {"error": str(e), "reason": e.reason})

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    service = EvaluatorService()
    httpd = ThreadingHTTPServer((host, port), make_handler(service))
    log_event("startup", host=host, port=port, cases=len(service.cases), facts=service.facts,
              prompt_versions=list(service.prompt_versions))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
