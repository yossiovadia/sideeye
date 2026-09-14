"""Unit tests for the capture-agnostic SessionTranscript schema."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.judge.transcript import (  # noqa: E402
    ESCALATION_BOUNDARY_NOTE,
    TranscriptError,
    first_user_ask,
    make_transcript,
    render,
    strip_escalation,
    validate_transcript,
)


def _t(**over):
    base = dict(
        session_id="s1", source="codex_rollout",
        turns=[{"role": "user", "text": "do X"}, {"role": "assistant", "text": "did X"}],
        model="glm", generation_usage={"input_tokens": 10, "output_tokens": 2},
    )
    base.update(over)
    return make_transcript(**base)


def test_make_transcript_valid():
    t = _t()
    assert t["session_id"] == "s1" and t["source"] == "codex_rollout"


def test_missing_session_id_rejected():
    with pytest.raises(TranscriptError):
        validate_transcript({"source": "x", "turns": [{"role": "user", "text": "hi"}]})


def test_empty_turns_rejected():
    with pytest.raises(TranscriptError):
        make_transcript(session_id="s", source="x", turns=[])


def test_bad_role_rejected():
    with pytest.raises(TranscriptError):
        make_transcript(session_id="s", source="x", turns=[{"role": "boss", "text": "hi"}])


def test_generation_usage_must_be_dict_or_none():
    with pytest.raises(TranscriptError):
        make_transcript(session_id="s", source="x",
                        turns=[{"role": "user", "text": "hi"}], generation_usage=5)


def test_first_user_ask():
    t = _t(turns=[{"role": "assistant", "text": "hello"},
                  {"role": "user", "text": "the real ask"},
                  {"role": "assistant", "text": "ok"}])
    assert first_user_ask(t) == "the real ask"


def test_render_includes_turns():
    r = render(_t())
    assert "USER:" in r and "do X" in r and "ASSISTANT:" in r and "did X" in r


def test_touched_files_default_empty():
    t = _t()
    assert t["touched_files"] == []


def test_touched_files_validated():
    with pytest.raises(TranscriptError):
        make_transcript(session_id="s", source="x",
                        turns=[{"role": "user", "text": "hi"}],
                        touched_files=[{"no_path": True}])
    # a valid touched_files list round-trips
    t = _t(touched_files=[{"path": "/x.py", "count": 2}])
    assert t["touched_files"] == [{"path": "/x.py", "count": 2}]


# ---------------------------------------------------------------------------
# strip_escalation — review mode must not review its own invocation.
# Turn shapes below are copied from what the claude_code adapter actually
# produces for a /escalate-all session (real jsonl, 2026-09-04).

_SKILL_BODY = ("Base directory for this skill: /Users/x/.claude/skills/escalate-all\n"
               "# /escalate-all — full session review\nRun sideeye review --current --yes")
_FIRING = "Firing up the judge, man."
_RAN_REVIEW = "[ran: sideeye review --current --yes --model=fable]"
_VERDICT_TOOL = ("[tool_result: Session : /tmp/s.jsonl\nJudge   : claude-fable-5, tier 1\n"
                 "Escalating to claude-fable-5...\n  score 2/5\n  judge cost: $0.0679")


def _real_work_turns():
    return [{"role": "user", "text": "write me a fibonacci"},
            {"role": "assistant", "text": "def fib(n): ..."}]


def test_strip_escalation_plain_session_untouched():
    t = _t(turns=_real_work_turns())
    t2, dropped = strip_escalation(t)
    assert t2 is t and dropped == 0


def test_strip_escalation_trims_in_flight_invocation():
    # THE bug shape: snapshot taken WHILE the review runs — skill body is a
    # sacred user turn, the session ends mid-call. Judge used to file a false
    # critical ("the session failed to escalate") on every escalate-all.
    t = _t(turns=_real_work_turns() + [
        {"role": "user", "text": _SKILL_BODY},
        {"role": "assistant", "text": _FIRING},
        {"role": "assistant", "text": _RAN_REVIEW},
    ])
    t2, dropped = strip_escalation(t)
    r = render(t2)
    assert dropped == 3
    assert "def fib" in r and "write me a fibonacci" in r
    assert "Base directory" not in r and "Firing up" not in r and _RAN_REVIEW not in r
    assert ESCALATION_BOUNDARY_NOTE in r          # judge is told where it stopped
    assert first_user_ask(t2) == "write me a fibonacci"
    # metadata rides through untouched
    assert t2["session_id"] == t["session_id"] and t2["model"] == t["model"]
    assert t2["generation_usage"] == t["generation_usage"]


def test_strip_escalation_completed_invocation_filters_without_truncating():
    # Re-review after the review answered: the tool_result exists and the human
    # spoke again — real work AFTER the escalation must survive.
    t = _t(turns=_real_work_turns() + [
        {"role": "user", "text": _SKILL_BODY},
        {"role": "assistant", "text": _FIRING},
        {"role": "assistant", "text": _RAN_REVIEW},
        {"role": "tool", "text": _VERDICT_TOOL},
        {"role": "assistant", "text": "the judge's verdict, verbatim"},
        {"role": "user", "text": "now fix the bug"},
        {"role": "assistant", "text": "fixed, tests pass"},
    ])
    t2, dropped = strip_escalation(t)
    r = render(t2)
    assert "Base directory" not in r
    assert "score 2/5" not in r and "judge cost" not in r   # no judging the judge
    assert _RAN_REVIEW not in r
    assert "now fix the bug" in r and "fixed, tests pass" in r


def test_strip_escalation_multiple_invocations_all_machinery_gone():
    t = _t(turns=[
        {"role": "user", "text": "ask 1"}, {"role": "assistant", "text": "ans 1"},
        {"role": "user", "text": _SKILL_BODY},
        {"role": "tool", "text": _VERDICT_TOOL},
        {"role": "user", "text": "ask 2"}, {"role": "assistant", "text": "ans 2"},
        {"role": "user", "text": _SKILL_BODY},
        {"role": "assistant", "text": _FIRING},
    ])
    t2, dropped = strip_escalation(t)
    r = render(t2)
    assert dropped == 4
    assert "ask 1" in r and "ans 1" in r and "ask 2" in r and "ans 2" in r
    assert "Base directory" not in r and "Firing up" not in r and "judge cost" not in r


def test_strip_escalation_machinery_only_falls_back_to_annotated_full():
    # Session whose only content IS the escalation: an empty packet would invite
    # the judge to fabricate, so keep everything but annotate the boundary.
    t = _t(turns=[{"role": "user", "text": _SKILL_BODY},
                  {"role": "assistant", "text": _FIRING}])
    t2, dropped = strip_escalation(t)
    r = render(t2)
    assert "Base directory" in r and ESCALATION_BOUNDARY_NOTE in r


def test_strip_escalation_human_quoting_verdict_is_not_machinery():
    # A human pasting judge output into a REAL question must stay reviewable —
    # the markers are role-aware for exactly this.
    t = _t(turns=[
        {"role": "user", "text": "write fib"},
        {"role": "assistant", "text": "def fib(n): ..."},
        {"role": "user", "text": _SKILL_BODY},
        {"role": "tool", "text": _VERDICT_TOOL},
        {"role": "user", "text": "the judge said 'score 2/5, judge cost: $0.07' — is that expected?"},
        {"role": "assistant", "text": "yes, that's the judge's price for a 4-turn session"},
    ])
    t2, dropped = strip_escalation(t)
    r = render(t2)
    assert "is that expected?" in r and "yes, that's the judge's price" in r
    assert "Base directory" not in r and "judge cost: $0.0679" not in r
