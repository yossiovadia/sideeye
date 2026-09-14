"""Unit tests for salience-tiered packet fitting — the fix that lets /escalate-all
review a session whose full transcript overflows the judge's context window by
evicting machine NOISE, never the human's intent. No network."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import sideeye.escalate as E  # noqa: E402
from sideeye.judge.transcript import make_transcript, render_budgeted  # noqa: E402


def _t(turns):
    return make_transcript(session_id="s", source="claude_code", turns=turns)


# --- render_budgeted: evict by salience, not by age ----------------------

def test_human_turns_are_sacred_even_under_tight_budget():
    t = _t([
        {"role": "user", "text": "SPEC: make it idempotent"},   # sacred
        {"role": "assistant", "text": "A" * 1000},              # tier-2 narration
        {"role": "tool", "text": "T" * 500},                    # tier-1 evidence
        {"role": "assistant", "text": "B" * 1000},              # tier-2 narration
        {"role": "user", "text": "no, revert that"},            # sacred (late spec!)
        {"role": "assistant", "text": "FINAL done"},            # tier-0 final turn
    ])
    text, cov = render_budgeted(t, char_budget=800)
    # Both human turns survive — including the LATE correction recency would drop.
    assert "make it idempotent" in text and "no, revert that" in text
    assert cov["kept"]["human"] == 2
    # The final assistant turn (the claims) survives; the two big narrations don't.
    assert "FINAL done" in text
    assert "A" * 1000 not in text and "B" * 1000 not in text
    assert cov["dropped"]["assistant"] == 2
    # Dropped runs leave an in-band marker so the judge is told, not fooled.
    assert "elided" in text


def test_evidence_tier_kept_before_narration():
    # Budget fits tier-0 + exactly ONE more item; the tool result (tier 1) must
    # win over the assistant narration (tier 2).
    t = _t([
        {"role": "user", "text": "go"},
        {"role": "assistant", "text": "narrate " * 40},   # tier-2
        {"role": "tool", "text": "ERROR: boom " * 20},    # tier-1
        {"role": "assistant", "text": "final"},           # tier-0
    ])
    # tier0 ~ "USER:\ngo" + "ASSISTANT:\nfinal" ~ 30 chars; give room for one ~250.
    text, cov = render_budgeted(t, char_budget=350)
    assert "boom" in text                 # evidence kept
    assert "narrate narrate" not in text  # narration dropped
    assert cov["kept"]["tool"] == 1 and cov["dropped"]["assistant"] == 1


def test_original_order_preserved():
    t = _t([
        {"role": "user", "text": "first"},
        {"role": "assistant", "text": "mid " * 200},   # will be dropped
        {"role": "user", "text": "second"},
        {"role": "assistant", "text": "last"},
    ])
    text, _ = render_budgeted(t, char_budget=200)
    assert text.index("first") < text.index("second") < text.index("last")


def test_fits_false_when_sacred_tier_alone_overflows():
    t = _t([{"role": "user", "text": "x" * 400}, {"role": "assistant", "text": "y"}])
    _, cov = render_budgeted(t, char_budget=10)
    assert cov["fits"] is False


def test_pathological_human_paste_is_capped():
    t = _t([{"role": "user", "text": "z" * 50_000}, {"role": "assistant", "text": "ok"}])
    text, cov = render_budgeted(t, char_budget=1_000_000)
    assert cov["human_capped"] == 1
    assert "chars elided" in text and len(text) < 50_000


# --- _fit_packet: full when it fits, tiered when it doesn't ---------------

def _tokmodel(base, key, body, model, max_tokens=None, user_agent=None):
    """Deterministic offline stand-in for estimate_cost: ~chars/4 of the real
    billable parts (system + user message + a flat tool-schema overhead)."""
    user = body["messages"][0]["content"]
    n = (len(body.get("system", "")) + len(user) + 2000) // 4
    return n, round(n * 1e-5, 4), True, ""


def _no_diff(budget_chars=None):
    return None


def test_fit_packet_ships_full_when_it_fits(monkeypatch):
    monkeypatch.setattr(E, "estimate_cost", _tokmodel)
    t = _t([{"role": "user", "text": "do a thing"},
            {"role": "assistant", "text": "did the thing"}])
    produced, toks, cost, exact, reason, cov = E._fit_packet(
        t, "do a thing", _no_diff, "RUBRIC",
        base_url="https://x", api_key="k", model="claude-fable-5")
    assert cov is None                 # no tiering needed
    assert "did the thing" in produced


def test_fit_packet_tiers_a_huge_session_and_keeps_all_human(monkeypatch):
    monkeypatch.setattr(E, "estimate_cost", _tokmodel)
    turns = [{"role": "user", "text": "SPEC one"}]
    for i in range(300):               # ~300 * 4000 chars ≈ 1.2M chars ≈ 300k tok
        turns.append({"role": "assistant", "text": f"narration {i} " + "n" * 4000})
        if i % 5 == 0:
            turns.append({"role": "tool", "text": f"tool {i} " + "t" * 800})
    turns.append({"role": "user", "text": "SPEC two: never amend commits"})
    turns.append({"role": "assistant", "text": "final summary"})
    t = _t(turns)
    produced, toks, cost, exact, reason, cov = E._fit_packet(
        t, "SPEC one", _no_diff, "RUBRIC",
        base_url="https://x", api_key="k", model="claude-fable-5")
    assert cov is not None                       # tiered
    assert cov["kept"]["human"] == 2             # every human turn kept
    assert "SPEC two: never amend commits" in produced   # late spec survived
    assert cov["dropped"]["assistant"] > 0       # narration evicted
    # And the result actually fits the window (that's the whole point).
    assert toks + E.DEFAULT_MAX_TOKENS + E._SAFETY_TOKENS <= 200_000


def test_fit_packet_converges_in_few_calls(monkeypatch):
    # P4.3: estimate-then-verify must fit a big overflowing session in a HANDFUL of
    # count_tokens calls, not the ~10-20 of the old binary search (each of which
    # re-uploaded the packet + stamped a phantom 0/0 metering row).
    calls = {"n": 0}
    def counting_tokmodel(*a, **k):
        calls["n"] += 1
        return _tokmodel(*a, **k)
    monkeypatch.setattr(E, "estimate_cost", counting_tokmodel)
    turns = [{"role": "user", "text": "SPEC"}]
    for i in range(400):                      # ~1.6M chars ≈ 400k tok — well over 200k
        turns.append({"role": "assistant", "text": f"n{i} " + "x" * 4000})
        if i % 4 == 0:
            turns.append({"role": "tool", "text": f"t{i} " + "y" * 900})
    t = _t(turns)
    produced, toks, *_r, cov = E._fit_packet(
        t, "SPEC", _no_diff, "RUBRIC", base_url="https://x", api_key="k", model="claude-fable-5")
    assert cov is not None                                    # tiered
    assert toks + E.DEFAULT_MAX_TOKENS + E._SAFETY_TOKENS <= 200_000   # fits
    assert calls["n"] <= E._MAX_FIT_ITERS + 1, f"{calls['n']} count_tokens calls (want ≤ few)"


def test_fit_packet_degrades_the_diff_when_transcript_floor_isnt_enough(monkeypatch):
    # Small transcript, but the full diff overflows on its own. The diff-overflow
    # rung must shrink the diff (respecting budget) and fit, flagging degradation.
    monkeypatch.setattr(E, "estimate_cost", _tokmodel)
    t = _t([{"role": "user", "text": "small ask"},
            {"role": "assistant", "text": "small answer"}])

    def make_diff(budget_chars=None):
        full = "D" * 3_000_000                       # ~750k tok — overflows alone
        return full if budget_chars is None else "D" * min(budget_chars, len(full))

    produced, toks, cost, exact, reason, cov = E._fit_packet(
        t, "small ask", make_diff, "RUBRIC",
        base_url="https://x", api_key="k", model="claude-fable-5")
    assert cov is not None and cov["diff_degraded"] is True
    assert toks + E.DEFAULT_MAX_TOKENS + E._SAFETY_TOKENS <= 200_000


def test_fit_packet_aborts_when_diff_cannot_shrink(monkeypatch):
    # make_diff ignores the budget (always huge) → even degraded it won't fit → abort.
    monkeypatch.setattr(E, "estimate_cost", _tokmodel)
    t = _t([{"role": "user", "text": "small ask"},
            {"role": "assistant", "text": "small answer"}])
    with pytest.raises(SystemExit):
        E._fit_packet(t, "small ask", lambda budget_chars=None: "D" * 3_000_000, "RUBRIC",
                      base_url="https://x", api_key="k", model="claude-fable-5")
