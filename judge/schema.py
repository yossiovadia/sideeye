"""Verdict schema + validation for the Side-Eye judge.

The judge returns its verdict through a forced tool call (structured output),
so the tool's `input` is already JSON — no parse-and-pray. This module is the
single source of truth for what a valid verdict looks like, used both by the
tool schema (judge.py) and by validation on parse.
"""
from __future__ import annotations

CORRECTNESS_VALUES = ("correct", "partially_correct", "incorrect")
SEVERITY_VALUES = ("minor", "major", "critical")
OVERALL_SEVERITY_VALUES = ("none", "minor", "major", "critical")

# Fields the judge itself must produce. run_judge.py adds the envelope fields
# (pair_id, rubric_version, judge_model, usage, cost) around these.
JUDGE_FIELDS = (
    "answered_what_was_asked",
    "correctness",
    "claims_supported",
    "score",
    "issues",
    "overall_severity",
    "summary",
)


class VerdictError(ValueError):
    """Raised when a verdict object does not conform to the schema."""


def _is_bool(x) -> bool:
    return isinstance(x, bool)


def _is_int(x) -> bool:
    # bool is a subclass of int in Python; reject it explicitly.
    return isinstance(x, int) and not isinstance(x, bool)


def validate_verdict(d):
    """Validate a judge-produced verdict dict in place; return it on success.

    Raises VerdictError with a precise message on any violation.
    """
    if not isinstance(d, dict):
        raise VerdictError(f"verdict must be an object, got {type(d).__name__}")

    missing = [f for f in JUDGE_FIELDS if f not in d]
    if missing:
        raise VerdictError(f"verdict missing required fields: {missing}")

    if not _is_bool(d["answered_what_was_asked"]):
        raise VerdictError("answered_what_was_asked must be a boolean")
    if not _is_bool(d["claims_supported"]):
        raise VerdictError("claims_supported must be a boolean")

    if d["correctness"] not in CORRECTNESS_VALUES:
        raise VerdictError(
            f"correctness must be one of {CORRECTNESS_VALUES}, got {d['correctness']!r}"
        )

    if not _is_int(d["score"]):
        raise VerdictError("score must be an integer")
    if not 1 <= d["score"] <= 5:
        raise VerdictError(f"score must be in 1..5, got {d['score']}")

    if d["overall_severity"] not in OVERALL_SEVERITY_VALUES:
        raise VerdictError(
            f"overall_severity must be one of {OVERALL_SEVERITY_VALUES}, "
            f"got {d['overall_severity']!r}"
        )

    if not isinstance(d["summary"], str) or not d["summary"].strip():
        raise VerdictError("summary must be a non-empty string")

    issues = d["issues"]
    if not isinstance(issues, list):
        raise VerdictError("issues must be a list")
    for i, it in enumerate(issues):
        if not isinstance(it, dict):
            raise VerdictError(f"issues[{i}] must be an object")
        if "description" not in it or "severity" not in it:
            raise VerdictError(f"issues[{i}] must have description and severity")
        if not isinstance(it["description"], str) or not it["description"].strip():
            raise VerdictError(f"issues[{i}].description must be a non-empty string")
        if it["severity"] not in SEVERITY_VALUES:
            raise VerdictError(
                f"issues[{i}].severity must be one of {SEVERITY_VALUES}, "
                f"got {it['severity']!r}"
            )

    return d


def is_flagged(verdict) -> bool:
    """Whether a verdict counts as flagging the response as defective.

    Used by the objective planted-defect evaluation. A response is "flagged"
    when the judge assigns a major/critical severity, scores it <= 2, or marks
    a claim unsupported. Minor issues on an otherwise-good answer do NOT count
    as a flag (they are not false positives against a clean answer).
    """
    return (
        verdict.get("overall_severity") in ("major", "critical")
        or verdict.get("score", 5) <= 2
        or verdict.get("claims_supported") is False
    )
