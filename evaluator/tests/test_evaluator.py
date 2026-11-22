import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from delusion_monitor import checker
from delusion_monitor.cli import main
from delusion_monitor.data import data_dir, load_batch, load_cases, parse_retention_facts
from delusion_monitor.server import make_handler
from delusion_monitor.service import EvaluationError, EvaluatorService

FACTS = {"production": 90, "dev": 14}


def test_runbook_facts_leave_test_undocumented():
    _, facts = load_cases()
    assert facts == FACTS
    assert "test" not in facts


def test_parser_ignores_tables_outside_retention_section():
    text = "## Other\n| Test | x | 30 days |\n## Audit log retention\n| Dev | x | 14 days |\n"
    assert parse_retention_facts(text) == {"dev": 14}


@pytest.mark.parametrize("item", load_batch(data_dir() / "cases.json"), ids=lambda i: i.case_id)
def test_six_cases_match_expected_verdicts(item):
    cases, facts = load_cases()
    assert checker.check(item.response, cases[item.case_id].environment, facts).verdict == item.expected_verdict


def test_cases_cover_required_categories_and_verdicts():
    cases, _ = load_cases()
    assert len(cases) == 6
    assert {c.category for c in cases.values()} == {"direct", "missing-information", "false-premise"}
    assert {c.expected_verdict for c in cases.values()} == set(checker.VERDICTS)


@pytest.mark.parametrize("item", load_batch(data_dir() / "batches" / "alert-demo.json"), ids=lambda i: i.response[:30])
def test_alert_batch_matches_expected_verdicts(item):
    cases, facts = load_cases()
    assert checker.check(item.response, cases[item.case_id].environment, facts).verdict == item.expected_verdict


def test_alert_batch_crosses_count_and_rate_thresholds():
    items = load_batch(data_dir() / "batches" / "alert-demo.json")
    flagged = sum(i.expected_verdict in checker.FLAGGED for i in items)
    assert len(items) >= 10  # alert minimum count
    assert flagged / len(items) > 0.30  # alert rate threshold
    # The six canned cases alone must not satisfy the minimum count.
    assert len(load_batch(data_dir() / "cases.json")) < 10


def test_headline_demo_365_days_is_contradicted():
    r = checker.check("365 days.", "production", FACTS)
    assert r.verdict == "contradicted"
    assert "365 days" in r.reason and "90 days" in r.reason


@pytest.mark.parametrize(
    "response,env,verdict",
    [
        ("3 months", "production", "pass"),                      # unit normalization
        ("Two weeks.", "dev", "pass"),
        ("ninety days", "production", "pass"),
        ("12 months", "production", "contradicted"),
        ("Retained for 90 days, not 7 days.", "production", "pass"),  # negation
        ("They are kept for 90 days rather than 365 days.", "production", "pass"),
        ("Test retention is undocumented.", "test", "pass"),
        ("That isn't documented in the runbook.", "test", "pass"),
        ("Test logs are kept forever.", "test", "unsupported"),
        ("Production is 90 days. Test retention is not documented.", "test", "pass"),  # other-env sentence skipped
        ("Logs are kept for a while.", "production", "unsupported"),
        ("The runbook doesn't specify production retention.", "production", "contradicted"),
    ],
)
def test_checker_rules(response, env, verdict):
    assert checker.check(response, env, FACTS).verdict == verdict


def test_unknown_labels_are_rejected_to_keep_cardinality_bounded():
    svc = EvaluatorService()
    with pytest.raises(EvaluationError):
        svc.evaluate("prod-retention", "365 days", "my-random-prompt")
    with pytest.raises(EvaluationError):
        svc.evaluate("not-a-case")


@pytest.fixture
def server():
    svc = EvaluatorService()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def _metric(base, line_prefix):
    body = urllib.request.urlopen(base + "/metrics").read().decode()
    for line in body.splitlines():
        if line.startswith(line_prefix):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{line_prefix} not in metrics")


def test_http_evaluate_logs_and_counts(server, caplog):
    key = 'delusion_evaluations_total{prompt_version="canned-v1",verdict="contradicted"}'
    assert _metric(server, key) == 0  # pre-initialized series
    with caplog.at_level("INFO", logger="delusion_monitor"):
        rec = _post(server + "/evaluate", {"case_id": "prod-retention", "response": "365 days."})
    assert rec["verdict"] == "contradicted"
    assert _metric(server, key) == 1
    logged = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    ev = next(e for e in logged if e["event"] == "evaluation")
    assert ev["question"] == "How long do we keep production EKS audit logs?"
    assert ev["response"] == "365 days." and ev["verdict"] == "contradicted" and "90 days" in ev["reason"]


def test_http_rejects_unknown_prompt_version(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(server + "/evaluate", {"case_id": "prod-retention", "prompt_version": "x"})
    assert e.value.code == 400
    assert _metric(server, 'delusion_rejected_requests_total{reason="unknown_prompt_version"}') == 1
    assert 'prompt_version="x"' not in urllib.request.urlopen(server + "/metrics").read().decode()


def test_alert_webhook_is_counted(server):
    _post(server + "/alerts", {"status": "firing", "alerts": [{"labels": {"alertname": "x"}, "status": "firing"}]})
    assert _metric(server, 'delusion_alert_notifications_total{status="firing"}') == 1


def test_cli_replay_exit_codes(server, capsys):
    assert main(["replay"]) == 0
    assert main(["replay", "--batch", str(data_dir() / "batches" / "alert-demo.json"), "--target", server]) == 0
    assert "flagged rate=75%" in capsys.readouterr().out
    assert main(["evaluate", "--case", "prod-retention", "--response", "90 days", "--expect", "contradicted"]) == 1
