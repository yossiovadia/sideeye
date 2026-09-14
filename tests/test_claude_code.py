"""Unit tests for the Claude Code adapter (#1b) and the source dispatcher."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.adapters import load_transcript  # noqa: E402
from sideeye.adapters.claude_code import parse_session  # noqa: E402
from sideeye.judge.transcript import first_user_ask  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"
CLAUDE = FIX / "sample_claude_session.jsonl"
CODEX = FIX / "sample_rollout.jsonl"


def test_parse_claude_session():
    t = parse_session(CLAUDE)
    assert t is not None
    assert t["source"] == "claude_code"
    assert t["model"] == "glm-5-2-fp8"


def test_skips_noise_and_thinking():
    t = parse_session(CLAUDE)
    # slash-command noise dropped; the real user ask survives.
    assert first_user_ask(t) == "write a Go function to add two ints"
    joined = " ".join(turn["text"] for turn in t["turns"])
    assert "local-command" not in joined
    assert "wants a simple add" not in joined  # thinking skipped
    assert "func Add" in joined                # assistant text kept
    assert "tool_result" in joined             # tool evidence kept


def test_generation_usage():
    t = parse_session(CLAUDE)
    gu = t["generation_usage"]
    assert gu["input_tokens"] == 1200
    assert gu["output_tokens"] == 40


def test_dispatcher_detects_both():
    ct = load_transcript(CODEX)
    cc = load_transcript(CLAUDE)
    assert ct["source"] == "codex_rollout"
    assert cc["source"] == "claude_code"
