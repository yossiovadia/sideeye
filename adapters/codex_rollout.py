"""Adapter #1: Codex CLI session rollout -> SessionTranscript.

Codex writes one rollout JSONL per session at
`~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`. Record types:
  - session_meta   : session_id, timestamp
  - turn_context   : model (the generation model)
  - response_item  : {type: "message", role, content:[{text}]} — the turns
  - event_msg      : token_count -> info.total_token_usage (cumulative usage)

NOTE (from the Side-Eye design review): a rollout is the *client's* view. If the
gateway mutates requests (prompt enrichment, compression, model rewrite), the log
shows a transcript that never crossed the wire. That's fine for the GLM POC (no
mutation on that route) but is the reason production capture must be gateway-side.
"""
from __future__ import annotations

import json
import pathlib

from sideeye.judge.transcript import make_transcript

# Leading injected turns we don't want in the judged transcript.
_INSTRUCTION_MARKERS = ("# AGENTS.md", "<INSTRUCTIONS>", "<permissions")


def _looks_like_instruction_dump(text: str) -> bool:
    head = text.lstrip()[:64]
    return any(head.startswith(m) or m in text[:200] for m in _INSTRUCTION_MARKERS)


def _message_text(payload) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return ""


def parse_rollout(path):
    """Parse one Codex rollout file into a SessionTranscript (or None if the
    file has no usable turns)."""
    path = pathlib.Path(path)
    session_id = path.stem
    created_at = None
    model = None
    usage = None
    turns = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rtype = obj.get("type")
            payload = obj.get("payload", {}) or {}

            if rtype == "session_meta":
                session_id = payload.get("session_id") or session_id
            elif rtype == "turn_context":
                model = payload.get("model") or model
            elif rtype == "response_item" and payload.get("type") == "message":
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue  # skip developer/system scaffolding
                text = _message_text(payload)
                if not text.strip():
                    continue
                if role == "user" and _looks_like_instruction_dump(text):
                    continue  # drop AGENTS.md / permissions injections
                turns.append({"role": role, "text": text})
            elif rtype == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info", {}) or {}
                tu = info.get("total_token_usage")
                if isinstance(tu, dict):
                    usage = {
                        "input_tokens": tu.get("input_tokens", 0),
                        "output_tokens": tu.get("output_tokens", 0),
                        "cached_input_tokens": tu.get("cached_input_tokens", 0),
                        "reasoning_output_tokens": tu.get("reasoning_output_tokens", 0),
                        "total_tokens": tu.get("total_tokens", 0),
                    }

    if not turns:
        return None
    return make_transcript(
        session_id=session_id, source="codex_rollout", turns=turns,
        model=model, created_at=created_at, generation_usage=usage,
    )
