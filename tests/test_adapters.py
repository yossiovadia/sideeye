"""Tests for session resolution — especially resolve_current_session's
robustness to a drifted shell cwd (the /tmp face-plant fix). No network."""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

import sideeye.adapters as A  # noqa: E402


@pytest.fixture(autouse=True)
def _no_harness_session_env(monkeypatch):
    """Heuristic tests must not be affected by a real harness session id."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


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


def test_resolve_current_env_session_id_wins_over_newer_sibling(monkeypatch, tmp_path):
    """The wrong-session race: a sibling session in the same project dir wrote
    more recently. The harness-exported session id must win over mtime."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    cwd = "/Users/x/proj"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    monkeypatch.setattr(pathlib.Path, "cwd", classmethod(lambda cls: pathlib.Path(cwd)))
    pdir = tmp_path / cwd.replace("/", "-")
    pdir.mkdir(parents=True)
    me = pdir / "aaaa-current-session.jsonl"
    me.write_text("{}", encoding="utf-8")
    os.utime(me, (1000, 1000))          # older...
    sibling = pdir / "bbbb-other-session.jsonl"
    sibling.write_text("{}", encoding="utf-8")
    os.utime(sibling, (2000, 2000))     # ...than the sibling's last write
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "aaaa-current-session")
    got, fell_back = A.resolve_current_session("claude")
    assert got == me and fell_back is False


def test_resolve_current_env_session_id_missing_falls_back_to_heuristic(monkeypatch, tmp_path):
    """Env id set but its transcript absent (e.g. pruned): old mtime behavior."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    cwd = "/Users/x/proj"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    monkeypatch.setattr(pathlib.Path, "cwd", classmethod(lambda cls: pathlib.Path(cwd)))
    pdir = tmp_path / cwd.replace("/", "-")
    pdir.mkdir(parents=True)
    old = pdir / "old.jsonl"
    old.write_text("{}", encoding="utf-8")
    os.utime(old, (1000, 1000))
    new = pdir / "new.jsonl"
    new.write_text("{}", encoding="utf-8")
    os.utime(new, (2000, 2000))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "zzzz-not-on-disk")
    got, fell_back = A.resolve_current_session("claude")
    assert got == new and fell_back is False


def test_resolve_current_env_session_id_found_in_ancestor_project_dir(monkeypatch, tmp_path):
    """Drifted cwd (sideeye/calibration) + harness env: find the session in an
    ancestor project dir, skipping closer project dirs that don't hold it."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    cwd = "/Users/x/proj/sideeye/calibration"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    monkeypatch.setattr(pathlib.Path, "cwd", classmethod(lambda cls: pathlib.Path(cwd)))
    parent_proj = tmp_path / "-Users-x-proj"
    parent_proj.mkdir(parents=True)
    me = parent_proj / "cccc-current-session.jsonl"
    me.write_text("{}", encoding="utf-8")
    # A closer project dir exists but does NOT hold the session file —
    # resolution must skip it and keep walking up.
    near = tmp_path / "-Users-x-proj-sideeye"
    near.mkdir(parents=True)
    other = near / "dddd-unrelated.jsonl"
    other.write_text("{}", encoding="utf-8")
    os.utime(other, (9999, 9999))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "cccc-current-session")
    got, fell_back = A.resolve_current_session("claude")
    assert got == me and fell_back is False


def test_resolve_current_env_session_id_in_unrelated_project_dir(monkeypatch, tmp_path):
    """The case the ancestor walk cannot do: cwd drifted to a tree that does NOT
    contain the session's project dir. The global UUID lookup still finds it,
    and a newer sibling in the cwd project dir must not shadow it."""
    monkeypatch.setattr(A, "CLAUDE_DIR", tmp_path)
    cwd = "/Users/x/elsewhere"
    monkeypatch.setattr(os, "getcwd", lambda: cwd)
    monkeypatch.setattr(pathlib.Path, "cwd", classmethod(lambda cls: pathlib.Path(cwd)))
    other_proj = tmp_path / "-Users-x-completely-different"
    other_proj.mkdir(parents=True)
    me = other_proj / "eeee-current-session.jsonl"
    me.write_text("{}", encoding="utf-8")
    cwd_proj = tmp_path / "-Users-x-elsewhere"
    cwd_proj.mkdir(parents=True)
    newer = cwd_proj / "ffff-newer-sibling.jsonl"
    newer.write_text("{}", encoding="utf-8")
    os.utime(newer, (9999, 9999))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "eeee-current-session")
    got, fell_back = A.resolve_current_session("claude")
    assert got == me and fell_back is False
