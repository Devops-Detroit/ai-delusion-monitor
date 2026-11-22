"""Load the runbook facts, test cases, and replay batches from the data directory."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROMPT_VERSION = "canned-v1"
# The prompt_version label is checked against this list, so the label set stays
# bounded. prompt-a and prompt-b are reserved for the LLM follow-up milestone.
DEFAULT_PROMPT_VERSIONS = ("canned-v1", "canned-v2", "prompt-a", "prompt-b")

ENVIRONMENT_ALIASES = {"production": "production", "prod": "production", "dev": "dev", "development": "dev", "test": "test"}


def data_dir() -> Path:
    env = os.environ.get("DELUSION_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data"


def allowed_prompt_versions() -> tuple[str, ...]:
    raw = os.environ.get("DELUSION_PROMPT_VERSIONS")
    if not raw:
        return DEFAULT_PROMPT_VERSIONS
    return tuple(v.strip() for v in raw.split(",") if v.strip())


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    environment: str
    question: str
    expected_behavior: str
    canned_response: str
    expected_verdict: str


@dataclass(frozen=True)
class BatchItem:
    case_id: str
    response: str
    expected_verdict: str
    prompt_version: str


_ROW_RE = re.compile(r"^\|\s*([A-Za-z]+)\s*\|[^|]*\|\s*(\d+)\s*days?\s*\|\s*$")


def parse_retention_facts(runbook_text: str) -> dict[str, int]:
    """Return {environment: retention_days} from the runbook's retention table.

    Only rows under the "## Audit log retention" heading are read. An environment
    with no row is undocumented, and the checker treats it that way.
    """
    facts: dict[str, int] = {}
    in_section = False
    for line in runbook_text.splitlines():
        if line.startswith("## "):
            in_section = line.strip().lower() == "## audit log retention"
            continue
        if not in_section:
            continue
        m = _ROW_RE.match(line.strip())
        if m:
            env = ENVIRONMENT_ALIASES.get(m.group(1).lower())
            if env:
                facts[env] = int(m.group(2))
    if not facts:
        raise ValueError("no retention facts found in runbook")
    return facts


def load_cases(root: Path | None = None) -> tuple[dict[str, Case], dict[str, int]]:
    root = root or data_dir()
    doc = json.loads((root / "cases.json").read_text())
    facts = parse_retention_facts((root / doc["runbook"]).read_text())
    cases = {c["id"]: Case(**c) for c in doc["cases"]}
    return cases, facts


def load_batch(path: Path) -> list[BatchItem]:
    """Load either cases.json (replays canned responses) or a batches/*.json file."""
    doc = json.loads(Path(path).read_text())
    default_pv = doc.get("prompt_version", DEFAULT_PROMPT_VERSION)
    if "cases" in doc:
        return [BatchItem(c["id"], c["canned_response"], c["expected_verdict"], default_pv) for c in doc["cases"]]
    return [
        BatchItem(i["case_id"], i["response"], i["expected_verdict"], i.get("prompt_version", default_pv))
        for i in doc["items"]
    ]
