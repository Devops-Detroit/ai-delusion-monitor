"""Command line interface.

  serve                          Run the HTTP evaluator.
  list-cases                     Print the six test cases.
  evaluate --case ID [...]       Evaluate one case, using its canned response or --response.
  replay   [--batch FILE] [...]  Replay a batch and compare verdicts with the expected verdicts.

evaluate and replay run in-process by default. With --target URL they POST to a
running evaluator, so that evaluator's metrics and logs record the results.
Exit codes: 0 when every verdict matches the expected verdict, 1 on a mismatch,
2 on a usage or HTTP error.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .data import data_dir, load_batch


def _post(target: str, payload: dict) -> dict:
    req = urllib.request.Request(
        target.rstrip("/") + "/evaluate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"error: {e.code} {e.read().decode()}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"error: cannot reach {target}: {e.reason}") from None


def _evaluator(target: str | None):
    if target:
        return lambda case_id, response, pv: _post(target, {"case_id": case_id, "response": response, "prompt_version": pv})
    from .service import EvaluatorService
    svc = EvaluatorService()
    return svc.evaluate


def cmd_list(_args) -> int:
    doc = json.loads((data_dir() / "cases.json").read_text())
    for c in doc["cases"]:
        print(f"{c['id']:<30} {c['category']:<20} expect={c['expected_verdict']:<13} {c['question']}")
    return 0


def cmd_evaluate(args) -> int:
    ev = _evaluator(args.target)
    try:
        rec = ev(args.case, args.response, args.prompt_version)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rec, indent=2))
    if args.expect and rec["verdict"] != args.expect:
        print(f"MISMATCH: expected {args.expect}, got {rec['verdict']}", file=sys.stderr)
        return 1
    return 0


def cmd_replay(args) -> int:
    items = load_batch(Path(args.batch))
    ev = _evaluator(args.target)
    mismatches = 0
    counts: dict[str, int] = {}
    for it in items:
        rec = ev(it.case_id, it.response, args.prompt_version or it.prompt_version)
        ok = rec["verdict"] == it.expected_verdict
        mismatches += not ok
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
        mark = "ok " if ok else "BAD"
        print(f"[{mark}] {it.case_id:<28} {rec['prompt_version']:<10} {rec['verdict']:<13} {it.response[:60]!r}")
    total = len(items)
    flagged = counts.get("contradicted", 0) + counts.get("unsupported", 0)
    print(f"\n{total} evaluated | " + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f" | flagged rate={flagged / total:.0%} | mismatches={mismatches}")
    return 1 if mismatches else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="delusion_monitor", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the HTTP evaluator")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)

    sub.add_parser("list-cases", help="print the test cases")

    e = sub.add_parser("evaluate", help="evaluate a single case")
    e.add_argument("--case", required=True)
    e.add_argument("--response", help="override the canned response")
    e.add_argument("--prompt-version", default=None)
    e.add_argument("--expect", choices=["pass", "contradicted", "unsupported"], help="exit 1 if the verdict differs")
    e.add_argument("--target", help="evaluator URL, e.g. http://localhost:8000")

    r = sub.add_parser("replay", help="replay a batch of canned responses")
    r.add_argument("--batch", default=str(data_dir() / "cases.json"), help="cases.json or a batches/*.json file")
    r.add_argument("--prompt-version", default=None, help="override the batch's prompt_version")
    r.add_argument("--target", help="evaluator URL, e.g. http://localhost:8000")

    args = p.parse_args(argv)
    from .service import configure_logging
    if args.cmd == "serve":
        configure_logging()
        from .server import serve
        serve(args.host, args.port)
        return 0
    if getattr(args, "target", None) is None:
        # In-process runs print the JSON evaluation log to stderr, so stdout stays readable.
        import logging
        logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    return {"list-cases": cmd_list, "evaluate": cmd_evaluate, "replay": cmd_replay}[args.cmd](args)
