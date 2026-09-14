"""The role-classification fix: Claude Code overloads role:user for human input,
tool results, AND harness-injected context. The adapter must split these so
salience-tiering keeps the human sacred and evicts machine noise. No network."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.adapters.claude_code import parse_session  # noqa: E402


def _write(tmp_path, records):
    p = tmp_path / "sess.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return p


def _u(content):
    return {"type": "user", "message": {"role": "user", "content": content}}


def _a(content, usage=None):
    return {"type": "assistant",
            "message": {"role": "assistant", "content": content,
                        "model": "qwen", "usage": usage or {"input_tokens": 10, "output_tokens": 5}}}


def test_roles_are_split_by_content(tmp_path):
    recs = [
        _u("please make it idempotent"),                                  # human -> user
        _a([{"type": "text", "text": "on it"},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/repo/x.py"}}]),  # assistant
        _u([{"type": "tool_result", "content": [{"type": "text", "text": "PASS 42 tests"}]}]),  # tool
        _u("<task-notification>\n<task-id>abc</task-id>\n</task-notification>"),  # system-inject
        _u("<command-name>/clear</command-name>"),                        # pure noise -> dropped
        _a([{"type": "text", "text": "done"}]),                          # assistant (final)
    ]
    t = parse_session(_write(tmp_path, recs))
    roles = [turn["role"] for turn in t["turns"]]
    assert roles == ["user", "assistant", "tool", "system", "assistant"]  # noise dropped
    # The human turn is the real ask, not tool output or a notification.
    users = [turn["text"] for turn in t["turns"] if turn["role"] == "user"]
    assert users == ["please make it idempotent"]
    # Tool result landed in the evidence tier, carrying its output.
    tools = [turn["text"] for turn in t["turns"] if turn["role"] == "tool"]
    assert "PASS 42 tests" in tools[0]
    # File edit still collected for the code artifact.
    assert t["touched_files"] == [{"path": "/repo/x.py", "count": 1}]


def test_tool_result_not_counted_as_human_intent(tmp_path):
    # A session that is mostly tool output must not present that output as the
    # human's words — first_user_ask (and the sacred tier) depend on this.
    recs = [
        _u([{"type": "tool_result", "content": [{"type": "text", "text": "big output " * 50}]}]),
        _u("the actual question"),
        _a([{"type": "text", "text": "answer"}]),
    ]
    t = parse_session(_write(tmp_path, recs))
    from sideeye.judge.transcript import first_user_ask
    assert first_user_ask(t) == "the actual question"   # not the tool_result
