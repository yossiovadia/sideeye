"""Unit tests for the code-review artifact builder (stage 1).

The artifact is what lets the judge review actual code instead of a 400-char
truncated narrative. These tests cover: touched-file diffing, new-file
handling, big-file degradation (view: partial), generated-file exclusion, the
manifest, and the adapter's extraction of touched file paths from tool_use
blocks. No network; git operations use a throwaway repo per test.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.adapters.claude_code import parse_session  # noqa: E402
from sideeye.judge.code_artifact import build_code_artifact  # noqa: E402


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError(f"git {args} failed: {r.stderr}")
    return r.stdout


def _make_repo(tmp_path):
    """A real git repo we can diff against. HEAD is the committed baseline."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _commit(repo, msg="init", allow_empty=False):
    _git(repo, "add", "-A")
    args = ["commit", "-q", "-m", msg, "--no-gpg-sign"]
    if allow_empty:
        args.append("--allow-empty")
    _git(repo, *args)


def test_empty_touched_files_returns_empty():
    assert build_code_artifact([], pathlib.Path(".")) == ""


def test_modified_file_shows_full_diff_with_markers(tmp_path):
    repo = _make_repo(tmp_path)
    f = repo / "judge.py"
    f.write_text("def old():\n    return 0\n")
    _commit(repo)
    # session modifies the file (working-tree change vs HEAD)
    f.write_text("def old():\n    return 1\n")

    art = build_code_artifact([{"path": str(f), "count": 1}], repo)
    assert "judge.py" in art
    assert "-    return 0" in art        # removed line (attribution marker)
    assert "+    return 1" in art        # added line
    assert "view: full" in art


def test_new_file_shows_full_content(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, allow_empty=True)
    # session creates a brand-new (untracked) file
    f = repo / "new_module.py"
    f.write_text("def fresh():\n    return 42\n")

    art = build_code_artifact([{"path": str(f), "count": 1}], repo)
    # new file: final content IS the diff — full content shown, not an empty diff
    assert "def fresh()" in art
    assert "return 42" in art
    assert "new file" in art.lower()


def test_big_file_degrades_to_partial_view(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    # A file big enough to exceed FULL_VIEW_LINE_CAP when diffed: modify one
    # line in a large file so -U999999 produces >cap lines.
    big = repo / "big.py"
    big.write_text("\n".join(f"line {i}" for i in range(600)) + "\n")
    _commit(repo)
    # change the last line
    big.write_text("\n".join(f"line {i}" for i in range(599)) + "\nCHANGED\n")

    # lower the cap so a 600-line diff triggers partial without a huge file
    from sideeye.judge import code_artifact as ca
    monkeypatch.setattr(ca, "FULL_VIEW_LINE_CAP", 100)

    art = build_code_artifact([{"path": str(big), "count": 1}], repo)
    assert "view: partial" in art
    # partial view must NOT dump all 600 lines
    assert art.count("\n") < 200


def test_generated_file_is_manifest_only(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, allow_empty=True)
    lock = repo / "Cargo.lock"
    lock.write_text('version = "1"\n' * 500)
    # Cargo.lock must be tracked-but-modified or untracked; untracked is fine
    art = build_code_artifact([{"path": str(lock), "count": 1}], repo)
    assert "manifest-only" in art
    assert "generated" in art.lower()
    # the lockfile's 500 lines must NOT be dumped into the artifact
    assert 'version = "1"' not in art


def test_manifest_has_edit_count_and_view(tmp_path):
    repo = _make_repo(tmp_path)
    f = repo / "a.py"
    f.write_text("x = 1\n")
    _commit(repo)
    f.write_text("x = 2\n")

    art = build_code_artifact([{"path": str(f), "count": 3}], repo)
    # edit count (3) is free thrash signal; view is full for a small file
    assert "3 edits" in art
    assert "view: full" in art


def test_deleted_file_does_not_crash(tmp_path):
    repo = _make_repo(tmp_path)
    f = repo / "gone.py"
    f.write_text("x = 1\n")
    _commit(repo)
    f.unlink()  # session deleted it (or it vanished)

    art = build_code_artifact([{"path": str(f), "count": 1}], repo)
    assert "deleted" in art or "no longer exists" in art


# --- adapter: touched_files extraction from tool_use ----------------------

def test_adapter_extracts_touched_files(tmp_path):
    """The adapter must collect Edit/Write file_path into touched_files so the
    code artifact knows what to diff. tool_use renders as a reference, not code."""
    session = tmp_path / "s.jsonl"
    session.write_text(
        json.dumps({"type": "user", "message": {"role": "user",
            "content": "fix the bug in foo.py"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
            "model": "m", "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [
                {"type": "text", "text": "editing now"},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/abs/foo.py", "old_string": "a", "new_string": "b"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/abs/foo.py", "old_string": "c", "new_string": "d"}},
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "/abs/bar.py", "content": "new"}},
            ]}}) + "\n"
    )
    t = parse_session(session)
    touched = {f["path"]: f["count"] for f in t["touched_files"]}
    assert touched == {"/abs/foo.py": 2, "/abs/bar.py": 1}  # foo edited twice = thrash signal
    # tool_use renders as a reference, not the 400-char code snippet
    joined = " ".join(turn["text"] for turn in t["turns"])
    assert "[Edit:" in joined and "/abs/foo.py" in joined
    assert "new_string" not in joined   # the code is NOT in the narrative anymore


def test_adapter_does_not_collect_bash_as_touched(tmp_path):
    """Bash commands aren't file edits — they must not pollute touched_files
    (their output is evidence, kept in tool_result, not diffed as code)."""
    session = tmp_path / "s.jsonl"
    session.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "run tests"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
            "model": "m", "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}},
            ]}}) + "\n"
    )
    t = parse_session(session)
    assert t["touched_files"] == []
    joined = " ".join(turn["text"] for turn in t["turns"])
    assert "[ran: pytest]" in joined
