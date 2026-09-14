"""Tests for session resolution — especially resolve_current_session's
robustness to a drifted shell cwd (the /tmp face-plant fix). No network."""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import sideeye.adapters as A  # noqa: E402


def test_resolve_current_prefers_cwd_project(monkeypatch, tmp_path):
    """When the shell IS in the session's project dir, use that session."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    cwd = "/Users/x/proj"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    pdir = tmp_path / cwd.replace("/", "-")
    pdir.mkdir(parents=True)
    sess = pdir / "sess.jsonl"
    sess.write_text("{}", encoding="utf-8")
    got, fell_back = A.resolve_current_session("claude")
    assert got == sess and fell_back is False


def test_resolve_current_falls_back_when_cwd_has_no_session(monkeypatch, tmp_path):
    """The face-plant fix: shell drifted to /private/tmp (no project dir), so fall
    back to the most-recently-written session across all projects."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    monkeypatch.setattr(os, "getcwd", lambda: "/private/tmp")  # mangles to a dir that won't exist
    other = tmp_path / "-Users-x-otherproj"
    other.mkdir(parents=True)
    old = other / "old.jsonl"
    old.write_text("{}", encoding="utf-8")
    new = other / "new.jsonl"
    new.write_text("{}", encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))   # newest by mtime == the active session
    got, fell_back = A.resolve_current_session("claude")
    assert got == new and fell_back is True


def test_resolve_current_walks_up_to_parent_project(monkeypatch, tmp_path):
    """Running from sideeye/calibration finds the praxis-ai project session."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    # Simulate cwd = /Users/x/proj/sideeye/calibration (no project dir for this)
    cwd = "/Users/x/proj/sideeye/calibration"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    monkeypatch.setattr(pathlib.Path, "cwd", classmethod(lambda cls: pathlib.Path(cwd)))
    # Parent /Users/x/proj has a project dir with a session
    parent_proj = tmp_path / "-Users-x-proj"
    parent_proj.mkdir(parents=True)
    sess = parent_proj / "sess.jsonl"
    sess.write_text("{}", encoding="utf-8")
    got, fell_back = A.resolve_current_session("claude")
    assert got == sess and fell_back is False


def test_resolve_current_walk_up_prefers_closest_ancestor(monkeypatch, tmp_path):
    """Walk-up picks the most specific (deepest) ancestor that has sessions."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    cwd = "/Users/x/proj/sub/deep"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    monkeypatch.setattr(pathlib.Path, "cwd", classmethod(lambda cls: pathlib.Path(cwd)))
    # /Users/x/proj has a session (grandparent)
    gp = tmp_path / "-Users-x-proj"
    gp.mkdir(parents=True)
    gp_sess = gp / "old.jsonl"
    gp_sess.write_text("{}", encoding="utf-8")
    os.utime(gp_sess, (1000, 1000))
    # /Users/x/proj/sub also has a session (parent — closer)
    parent = tmp_path / "-Users-x-proj-sub"
    parent.mkdir(parents=True)
    p_sess = parent / "closer.jsonl"
    p_sess.write_text("{}", encoding="utf-8")
    os.utime(p_sess, (2000, 2000))
    got, fell_back = A.resolve_current_session("claude")
    assert got == p_sess and fell_back is False


def test_resolve_current_none_when_no_sessions_anywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    monkeypatch.setattr(os, "getcwd", lambda: "/private/tmp")
    got, fell_back = A.resolve_current_session("claude")
    assert got is None and fell_back is True
