"""Rendering layer invariants: (1) pipes never see ANSI — only a real TTY
(or SIDEEYE_COLOR=always) gets color, so JSONL files, Claude Code's Bash
capture, and the skill's verbatim-presentation flow stay plain text (the
hindsight ANSI-flood lesson); (2) wrapping/tags never lose verdict content —
score, summary words, every issue description must survive in both modes."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.judge import style  # noqa: E402

_RECORD = {
    "score": 4,
    "correctness": "correct",
    "claims_supported": False,
    "overall_severity": "major",
    "summary": "The scaffold is well-built " + "but the response overstates its evidence. " * 6,
    "issues": [
        {"severity": "major", "description": "X" * 200},
        {"severity": "minor", "description": "short nit"},
    ],
    "judge_cost_usd": 0.3872,
}


def test_plain_mode_has_no_ansi_even_with_forced_env(monkeypatch):
    monkeypatch.delenv("SIDEEYE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert "\033[" not in style.render_verdict(_RECORD, "/tmp/x.jsonl")


def test_color_mode_tags_score_and_flags(monkeypatch):
    monkeypatch.setenv("SIDEEYE_COLOR", "always")
    out = style.render_verdict(_RECORD, "/tmp/x.jsonl")
    assert "\033[" in out
    assert "[major]" in out and "[minor]" in out
    assert "4/5" in out and "claims UNSUPPORTED" in out
    assert "/tmp/x.jsonl" in out


def test_verdict_content_survives_wrapping():
    out = style.render_verdict(_RECORD, "/tmp/x.jsonl", enabled=False)
    # wrapping inserts whitespace, so compare word streams, not raw substrings
    words = " ".join(out.split())
    assert "The scaffold is well-built" in words
    assert words.count("X") == 200     # long issue body survives wrapping intact
    assert "short nit" in words
    assert all(len(line) <= 110 for line in out.splitlines())  # no 400-char walls


def test_advice_renders_section_labels_and_bullets():
    text = ("**Recommendation** — don't guess with `--model=opus`; " +
            "check the raw response instead, " * 5 +
            "\n\n**Confidence** — Medium.\n- first bullet\n- second bullet")
    out = style.render_advice(text, enabled=False)
    assert "RECOMMENDATION" in out and "CONFIDENCE" in out
    assert "`--model=opus`" not in out          # backticks consumed, content kept
    assert "--model=opus" in out
    assert "first bullet" in out and "second bullet" in out
    assert all(len(line) <= 110 for line in out.splitlines())


def test_no_color_env_wins_over_always(monkeypatch):
    monkeypatch.setenv("SIDEEYE_COLOR", "always")
    monkeypatch.setenv("NO_COLOR", "1")
    assert not style.color_enabled()
