"""Terminal rendering for judge output — humans are the audience here, not
the model. Verdicts and advice are recorded as JSONL regardless; this module
only decides how the interactive print LOOKS: severity-colored tags, a
scored header, wrapped paragraphs instead of 400-char walls, and bold
section labels for the free-form advice text.

Color policy (the hindsight lesson: ANSI escape floods ruined non-TTY
captures): paint only when stdout is a real terminal. Piped output — files,
Claude Code's Bash capture, scripts — stays plain text automatically.
NO_COLOR=1 forces plain; SIDEEYE_COLOR=always forces color (tests/demos)."""
from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap

_RESET, _BOLD, _DIM = "\033[0m", "\033[1m", "\033[2m"
_RED, _YELLOW, _GREEN, _CYAN, _MAG = "\033[31m", "\033[33m", "\033[32m", "\033[36m", "\033[35m"

# severity -> (paint-fn, plain tag). Order of concern: red > yellow > green.
_SEV = {
    "critical": (_BOLD + _RED, "critical"),
    "major": (_RED, "major"),
    "minor": (_YELLOW, "minor"),
    "none": (_GREEN, "none"),
}


def color_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("SIDEEYE_COLOR", "").lower() == "always":
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _width() -> int:
    return max(60, min(100, shutil.get_terminal_size((96, 24)).columns))


class Painter:
    """Paints only when enabled; otherwise every call is the identity."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def p(self, s: str, *codes: str) -> str:
        return ("".join(codes) + s + _RESET) if self.enabled and codes else s

    def bold(self, s): return self.p(s, _BOLD)
    def dim(self, s): return self.p(s, _DIM)

    def sev_tag(self, severity: str) -> str:
        code, label = _SEV.get((severity or "").lower(), (_YELLOW, severity or "?"))
        return self.p(f"[{label}]", code, _BOLD)

    def score(self, score, max_score: int = 5) -> str:
        s = f"{score}/{max_score}"
        try:
            n = int(score)
        except (TypeError, ValueError):
            return s
        code = _GREEN if n >= 4 else _YELLOW if n == 3 else _BOLD + _RED
        return self.p(s, code, _BOLD)

    def flag(self, ok: bool, yes: str, no: str) -> str:
        return self.p(yes if ok else no, _GREEN if ok else _BOLD + _RED, _BOLD)


def render_verdict(record: dict, out_path: str, *, enabled: bool | None = None) -> str:
    """The interactive verdict block: scored header, wrapped summary, and
    severity-colored issue tags with hanging indents. Record shape is the
    JSONL record (score, correctness, claims_supported, overall_severity,
    summary, issues[])."""
    pt = Painter(color_enabled() if enabled is None else enabled)
    w = _width()
    out = []

    claims = pt.flag(bool(record.get("claims_supported")), "claims supported", "claims UNSUPPORTED")
    sev = pt.sev_tag(record.get("overall_severity", ""))
    out.append(f"  score {pt.score(record.get('score', '?'))}   "
               f"correctness: {pt.bold(str(record.get('correctness', '?')))}   {claims}   severity {sev}")
    out.append("")
    for line in textwrap.wrap(record.get("summary", ""), width=w - 4) or ["(no summary)"]:
        out.append(f"  {line}")

    issues = record.get("issues") or []
    if issues:
        out.append("")
        out.append(pt.dim(f"  {'-' * 3} issues ({len(issues)}) {'-' * max(0, w - 18 - len(str(len(issues))))}"))
        for it in issues:
            tag = pt.sev_tag(it.get("severity", ""))
            body = str(it.get("description", "")).strip()
            lines = textwrap.wrap(body, width=w - 11) or [""]
            out.append(f"    {tag} {lines[0]}")
            for cont in lines[1:]:
                out.append(f"         {cont}")

    out.append("")
    out.append(f"  judge cost: ${record['judge_cost_usd']:.4f}  ->  " + pt.dim(str(out_path)))
    out.append(pt.dim("  (separate escalated stream — not pooled with random samples)"))
    return "\n".join(out)


_BOLD_LABEL = re.compile(r"^\s*\*\*(.+?)\*\*\s*[-—]?\s*(.*)$")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def render_advice(text: str, *, enabled: bool | None = None) -> str:
    """Advice is free-form prose the judge writes in loose markdown. Render:
    **Section** labels go bold, `code` spans go cyan, everything wraps."""
    pt = Painter(color_enabled() if enabled is None else enabled)
    w = _width()
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append("")
            continue
        indent = "  "
        if m := _BOLD_LABEL.match(line):
            label, rest = m.group(1), m.group(2)
            head = pt.bold(label.rstrip(":").upper())
            body = _INLINE_CODE.sub(lambda mm: pt.p(mm.group(1), _CYAN), rest)
            wrapped = textwrap.wrap(body, width=w - len(indent)) or [""]
            out.append(f"{indent}{head}")
            for cl in wrapped:
                out.append(f"{indent}{cl}")
        elif line.startswith(("- ", "* ")):
            body = _INLINE_CODE.sub(lambda mm: pt.p(mm.group(1), _CYAN), line[2:])
            bullets = textwrap.wrap(body, width=w - len(indent) - 4) or [""]
            out.append(f"{indent}{pt.p('•', _MAG)} {bullets[0]}")
            for cont in bullets[1:]:
                out.append(f"{indent}  {cont}")
        else:
            body = _INLINE_CODE.sub(lambda mm: pt.p(mm.group(1), _CYAN), line)
            for cl in textwrap.wrap(body, width=w - len(indent)) or [""]:
                out.append(f"{indent}{cl}")
    return "\n".join(out)


def render_error(msg: str, *, enabled: bool | None = None) -> str:
    pt = Painter(color_enabled(sys.stderr) if enabled is None else enabled)
    return pt.p(f"ERROR: {msg}", _BOLD + _RED)
