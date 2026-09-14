"""Unit tests for the Codex rollout adapter (adapter #1)."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.adapters.codex_rollout import parse_rollout  # noqa: E402
from sideeye.judge.transcript import first_user_ask  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sample_rollout.jsonl"


def test_parse_rollout_basic():
    t = parse_rollout(FIXTURE)
    assert t is not None
    assert t["session_id"] == "test-session-123"
    assert t["source"] == "codex_rollout"
    assert t["model"] == "glm-5-2-fp8"


def test_skips_developer_and_instruction_dumps():
    t = parse_rollout(FIXTURE)
    # developer scaffolding + the AGENTS.md/<INSTRUCTIONS> user turn are dropped;
    # only the real user turn + the assistant answer remain.
    assert len(t["turns"]) == 2
    roles = [turn["role"] for turn in t["turns"]]
    assert roles == ["user", "assistant"]
    assert first_user_ask(t) == "write a Go function to add two ints"
    assert "AGENTS.md" not in first_user_ask(t)


def test_extracts_generation_usage():
    t = parse_rollout(FIXTURE)
    gu = t["generation_usage"]
    assert gu["input_tokens"] == 1000
    assert gu["output_tokens"] == 200
    assert gu["total_tokens"] == 1250


def test_no_turns_returns_none(tmp_path):
    empty = tmp_path / "rollout-empty.jsonl"
    empty.write_text('{"type":"event_msg","payload":{"type":"task_started"}}\n', encoding="utf-8")
    assert parse_rollout(empty) is None
