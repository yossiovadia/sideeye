"""The retry path must stay protocol-correct: when the first record_verdict is
malformed, the retry echoes the assistant's tool_use, so the next user message
MUST answer it with a tool_result — a plain-text nudge gets a 400 from Anthropic
('tool_use ids were found without tool_result blocks') and burns the paid first
call. This test inspects the retry body offline (call_judge mocked). No network."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.judge import judge as J  # noqa: E402
from sideeye.judge.schema import VerdictError  # noqa: E402


def _malformed_first():
    # Forced tool_choice honored, but input is missing required fields -> VerdictError.
    return {"content": [{"type": "tool_use", "id": "toolu_ABC123",
                         "name": "record_verdict", "input": {"summary": "incomplete"}}],
            "usage": {"input_tokens": 100, "output_tokens": 10}}


def _valid_verdict_response():
    return {"content": [{"type": "tool_use", "id": "toolu_DEF456", "name": "record_verdict",
                         "input": {"answered_what_was_asked": True, "correctness": "correct",
                                   "claims_supported": True, "score": 4, "issues": [],
                                   "overall_severity": "none", "summary": "ok"}}],
            "usage": {"input_tokens": 50, "output_tokens": 20}}


def test_retry_answers_tool_use_with_tool_result(monkeypatch):
    bodies = []

    def fake_call(base, key, body, timeout=60, **kwargs):
        bodies.append(body)
        return _malformed_first() if len(bodies) == 1 else _valid_verdict_response()

    monkeypatch.setattr(J, "call_judge", fake_call)
    verdict, meta = J.judge("asked", "produced", "RUBRIC",
                            base_url="https://x", api_key="k", model="claude-fable-5")

    assert meta["retries"] == 1
    retry = bodies[1]
    roles = [m["role"] for m in retry["messages"]]
    assert roles == ["user", "assistant", "user"]
    # messages.1 (assistant) carries the malformed tool_use...
    tu = [b for b in retry["messages"][1]["content"]
          if isinstance(b, dict) and b.get("type") == "tool_use"]
    assert tu and tu[0]["id"] == "toolu_ABC123"
    # ...and messages.2 (user) MUST answer it with a matching tool_result.
    m2 = retry["messages"][2]["content"]
    assert isinstance(m2, list)
    tr = [b for b in m2 if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert tr and tr[0]["tool_use_id"] == "toolu_ABC123"
    assert "invalid" in tr[0]["content"]        # the corrective nudge rides inside it
    # cost accumulates across both calls
    assert meta["input_tokens"] == 150


def test_retry_success_returns_valid_verdict(monkeypatch):
    calls = {"n": 0}

    def fake_call(base, key, body, timeout=60, **kwargs):
        calls["n"] += 1
        return _malformed_first() if calls["n"] == 1 else _valid_verdict_response()

    monkeypatch.setattr(J, "call_judge", fake_call)
    verdict, meta = J.judge("a", "p", "R", base_url="https://x", api_key="k")
    assert verdict["summary"] == "ok" and meta["retries"] == 1


def test_refusal_fails_fast_with_diagnosis_and_no_retry(monkeypatch):
    """A content-policy refusal (stop_reason=refusal, no content) must NOT
    trigger the corrective retry — the retry would refuse again on a second
    charge. The VerdictError must carry the diagnosis so escalate.py's error
    record says WHY (2026-09-03: a 106k-token advice packet died as opaque
    'judge returned no text', indistinguishable from a transport bug)."""
    calls = {"n": 0}

    def fake_call(base, key, body, timeout=60, **kwargs):
        calls["n"] += 1
        return {"content": [], "stop_reason": "refusal",
                "usage": {"input_tokens": 106000, "output_tokens": 0}}

    monkeypatch.setattr(J, "call_judge", fake_call)
    import pytest
    with pytest.raises(VerdictError, match=r"stop_reason=refusal.*content policy"):
        J.judge("a", "p", "R", base_url="https://x", api_key="k")
    assert calls["n"] == 1  # failed fast — no second paid call
