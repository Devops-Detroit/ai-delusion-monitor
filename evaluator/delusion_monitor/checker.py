"""Deterministic grounding checks for retention answers.

Verdicts:
  pass          The response agrees with the runbook. For an undocumented fact,
                it says the fact is undocumented.
  contradicted  The response asserts a value that differs from a documented fact.
  unsupported   The response asserts something the runbook does not document,
                or it does not answer from the runbook at all.

Method:
  1. Split the response into sentences. Skip a sentence that names a different
     environment and does not name the case's environment.
  2. Find durations such as "90 days", "3 months", "a year", or "two weeks" and
     convert them to days (week=7, month=30, year=365).
  3. Ignore a duration that is negated: "not 7 days", "rather than 7 days".
  4. Compare the remaining durations with the runbook fact for the case's environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PASS, CONTRADICTED, UNSUPPORTED = "pass", "contradicted", "unsupported"
VERDICTS = (PASS, CONTRADICTED, UNSUPPORTED)
FLAGGED = (CONTRADICTED, UNSUPPORTED)

UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fourteen": 14, "thirty": 30, "ninety": 90,
}
_NUM = r"\d+|" + "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))
DURATION_RE = re.compile(rf"\b({_NUM})[\s-]*(day|week|month|year)s?\b", re.IGNORECASE)
# Matched against the text just before a duration, in the same sentence.
NEGATION_RE = re.compile(
    r"(\bnot|n't|\bnever|\brather than|\binstead of)\s+(?:[\w']+\s+){0,2}$", re.IGNORECASE
)
ENV_PATTERNS = {
    "production": re.compile(r"\bprod(uction)?\b", re.IGNORECASE),
    "dev": re.compile(r"\bdev(elopment)?\b", re.IGNORECASE),
    "test": re.compile(r"\btest(ing)?\b", re.IGNORECASE),
}
UNDOCUMENTED_RE = re.compile(
    r"\bundocumented\b"
    r"|\b(?:is|are|isn't|aren't)\s+not\s+(?:documented|specified|defined|listed|stated|covered)\b"
    r"|\b(?:isn't|aren't)\s+(?:documented|specified|defined|listed|stated|covered)\b"
    r"|\b(?:does not|doesn't|do not|don't)\s+(?:document|specify|define|list|state|mention|say|include|cover)\b"
    r"|\bno\s+(?:documented\s+)?retention(?:\s+period)?\s+(?:is\s+)?(?:documented|specified|defined|listed)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+")


@dataclass(frozen=True)
class Duration:
    text: str
    days: int


@dataclass(frozen=True)
class Result:
    verdict: str
    reason: str
    claimed_days: tuple[int, ...]


def _to_days(num: str, unit: str) -> int:
    n = int(num) if num.isdigit() else WORD_NUMBERS[num.lower()]
    return n * UNIT_DAYS[unit.lower()]


def asserted_durations(response: str, environment: str) -> list[Duration]:
    """Durations the response asserts about `environment`, with negated ones removed."""
    found: list[Duration] = []
    for sentence in _SENTENCE_SPLIT.split(response.strip()):
        mentioned = {env for env, pat in ENV_PATTERNS.items() if pat.search(sentence)}
        if mentioned and environment not in mentioned:
            continue  # this sentence is about another environment
        for m in DURATION_RE.finditer(sentence):
            if NEGATION_RE.search(sentence[: m.start()]):
                continue
            found.append(Duration(m.group(0), _to_days(m.group(1), m.group(2))))
    return found


def _fmt(durations: list[Duration]) -> str:
    parts = []
    for d in durations:
        plain = d.text.lower() in (f"{d.days} days", f"{d.days} day")
        parts.append(f'"{d.text}"' if plain else f'"{d.text}" (= {d.days} days)')
    return ", ".join(parts)


def check(response: str, environment: str, facts: dict[str, int]) -> Result:
    claims = asserted_durations(response, environment)
    days = tuple(d.days for d in claims)
    acknowledges_gap = bool(UNDOCUMENTED_RE.search(response))
    fact = facts.get(environment)

    if fact is None:
        if claims:
            return Result(UNSUPPORTED, f"Runbook does not document {environment} retention, but the response claims {_fmt(claims)}.", days)
        if acknowledges_gap:
            return Result(PASS, f"Response correctly says {environment} retention is not documented.", days)
        return Result(UNSUPPORTED, f"Runbook does not document {environment} retention, and the response does not say so.", days)

    wrong = [d for d in claims if d.days != fact]
    if wrong:
        return Result(CONTRADICTED, f"Response claims {_fmt(wrong)}; runbook says {environment} retention is {fact} days.", days)
    if claims:
        return Result(PASS, f"Response matches the runbook: {environment} retention is {fact} days.", days)
    if acknowledges_gap:
        return Result(CONTRADICTED, f"Response says {environment} retention is not documented; runbook says {fact} days.", days)
    return Result(UNSUPPORTED, f"Response does not state the documented {environment} retention of {fact} days.", days)
