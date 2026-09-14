"""Unit tests for the context-window guard and legible provider errors — the
fix for the 474k-token escalation that 400'd and still cost ~$4.77. No network."""
from __future__ import annotations

import pathlib
import sys

import pytest
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.judge import judge as J  # noqa: E402


# --- context_guard: the hard limit --max-cost missed ---------------------

def test_context_guard_blocks_the_474k_overflow():
    # The exact shape of the incident: 474,074 tokens into Fable's 200k window.
    prob = J.context_guard(474_074, "claude-fable-5")
    assert prob is not None
    assert "474,074" in prob and "200,000" in prob
    assert "not sending it" in prob            # refused, no spend


def test_context_guard_allows_a_fitting_packet():
    assert J.context_guard(50_000, "claude-fable-5") is None


def test_context_guard_accounts_for_output_headroom():
    # Input alone fits, but input + max_tokens output does not → still blocked.
    w = J.context_window("claude-opus-4-8")          # 200_000
    assert J.context_guard(w - 100, "claude-opus-4-8", max_tokens=1024) is not None
    assert J.context_guard(w - 2000, "claude-opus-4-8", max_tokens=1024) is None


def test_context_guard_is_model_agnostic_across_the_catalog():
    # Every routed Claude model is a 200k window, so any --model overflows at 474k
    # (this is why "model=fable" vs another choice changed nothing).
    for m in ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-5",
              "claude-haiku-4-5-20251001"):
        assert J.context_guard(474_074, m) is not None


def test_context_window_falls_back_for_unknown_model():
    assert J.context_window("some-future-model") == J.DEFAULT_CONTEXT_WINDOW


# --- call_judge: surface the provider's error body, not "400 Bad Request" -

class _Resp:
    def __init__(self, status, reason, payload=None, text=""):
        self.status_code = status
        self.reason = reason
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_call_judge_surfaces_anthropic_error_message(monkeypatch):
    payload = {"type": "error",
               "error": {"type": "invalid_request_error",
                         "message": "prompt is too long: 474074 tokens > 200000 maximum"}}
    monkeypatch.setattr(J.requests, "post",
                        lambda *a, **k: _Resp(400, "Bad Request", payload=payload))
    with pytest.raises(requests.HTTPError) as ei:
        J.call_judge("https://api.anthropic.com", "k", {"model": "claude-fable-5"})
    msg = str(ei.value)
    assert "prompt is too long" in msg and "200000" in msg   # the WHY is visible


def test_call_judge_falls_back_to_text_when_body_not_json(monkeypatch):
    monkeypatch.setattr(J.requests, "post",
                        lambda *a, **k: _Resp(502, "Bad Gateway", text="upstream boom"))
    with pytest.raises(requests.HTTPError) as ei:
        J.call_judge("https://api.anthropic.com", "k", {"model": "claude-fable-5"})
    assert "upstream boom" in str(ei.value)


# --- User-Agent: makes escalate its own "client" on the metering dashboard ----

def test_call_judge_and_count_tokens_send_custom_user_agent(monkeypatch):
    seen = []
    def fake_post(url, headers=None, json=None, timeout=None):
        seen.append((headers or {}).get("user-agent"))
        payload = {"input_tokens": 5} if url.endswith("count_tokens") else {"content": [], "usage": {}}
        return _Resp(200, "OK", payload=payload)
    monkeypatch.setattr(J.requests, "post", fake_post)
    J.call_judge("https://api.anthropic.com", "k", {"model": "m"}, user_agent="sideeye-review")
    J.count_tokens("https://api.anthropic.com", "k", {"model": "m"}, user_agent="sideeye-advise")
    assert seen == ["sideeye-review", "sideeye-advise"]   # not python-requests


def test_user_agent_defaults_to_sideeye(monkeypatch):
    seen = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen["ua"] = (headers or {}).get("user-agent")
        return _Resp(200, "OK", payload={"content": [], "usage": {}})
    monkeypatch.setattr(J.requests, "post", fake_post)
    J.call_judge("https://api.anthropic.com", "k", {"model": "m"})
    assert seen["ua"].startswith("sideeye")
