#!/usr/bin/env python3
"""Judge baseline over the calibration pool.

Loads calibration_pools.jsonl, grades each pair against the Side-Eye rubric
(strict-JSON verdicts), and scores
against hidden ground truth:
  recall        = planted defects the judge flagged (score<=3 or major/critical severity)
  false_flags   = clean pairs the judge flagged
Writes <judge_id>_verdicts.jsonl (checkpointed) + <judge_id>_report.md, so
different judges (local 27B vs claude-fable-5) can share one calibration dir.
Each verdict record carries `usage` — provider token counts, summed across
retries for that pair — so total cost can be computed from the verdicts file.

Judge is configurable via env so the same frozen pools can be graded by any
judge on any machine:
  SIDEEYE_JUDGE_BASE_URL  (default http://100.67.159.20:11434/v1/chat/completions — llama.cpp OpenAI-shape)
  SIDEEYE_JUDGE_API_KEY   (default "local")
  SIDEEYE_JUDGE_MODEL     (default qwen3.8-uncensored:4090)
  SIDEEYE_CALIB_JUDGE_ID  (default derived from model; used in output filenames)
  SIDEEYE_JUDGE_API_STYLE openai|anthropic  (default auto: anthropic if base url mentions anthropic
  or ends in /v1/messages, else openai)
Anthropic-style example (Fable):
  SIDEEYE_JUDGE_BASE_URL=https://api.anthropic.com/v1/messages \
  SIDEEYE_JUDGE_API_KEY=sk-ant-... SIDEEYE_JUDGE_MODEL=claude-fable-5 \
  SIDEEYE_CALIB_JUDGE_ID=fable-5 python3 evaluate.py
Stop early: touch sideeye/calibration/STOP.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request

import requests

BASE = os.environ.get("SIDEEYE_JUDGE_BASE_URL", "http://100.67.159.20:11434/v1/chat/completions")
MODEL = os.environ.get("SIDEEYE_JUDGE_MODEL", "qwen3.8-uncensored:4090")
API_KEY = os.environ.get("SIDEEYE_JUDGE_API_KEY", "local")
JUDGE_ID = os.environ.get("SIDEEYE_CALIB_JUDGE_ID") or MODEL.replace("/", "_").replace(":", "_")
API_STYLE = os.environ.get("SIDEEYE_JUDGE_API_STYLE") or (
    "anthropic" if ("anthropic" in BASE or BASE.rstrip("/").endswith("/v1/messages")) else "openai")

HERE = pathlib.Path(__file__).resolve().parent
POOLS = HERE / "calibration_pools.jsonl"
VERDICTS = HERE / f"{JUDGE_ID}_verdicts.jsonl"
PROGRESS = HERE / "progress.jsonl"
REPORT = HERE / f"{JUDGE_ID}_report.md"
STOP = HERE / "STOP"
UA = "sideeye-calib/0.1"
# Some frontier models (claude-fable-5) reject `temperature` with a 400.
# When the server tells us, drop it for the rest of the run.
_temperature_dropped = False


class JudgeRefused(Exception):
    """stop_reason=refusal — retrying the identical prompt is futile."""

RUBRIC = """You are a strict code reviewer GRADING a response. You are NOT answering the request; judge only the response given, on its own terms.

Grade: 1) Answered what was asked. 2) Correctness: API names, semantics, types, off-by-one/edge cases. A plausible-but-wrong API claim is an incorrectness, not a nit. **A wrong factual/API claim in the explanation is a defect even if the code itself is correct** — never shrug-accept a wrong explanation because the code works; give it at least `major` severity and a score of 3 or below. 3) Claims vs evidence: treat unsupported success claims ("tests pass", "O(1)", "verified") as defects.

Reply with STRICT JSON only (no fences, no prose):
{"answered_what_was_asked": bool, "correctness": "correct|partially_correct|incorrect",
 "claims_supported": bool, "score": 1-5 (integer, never above 5), "overall_severity": "none|minor|major|critical",
 "issues": [{"description": str, "severity": "minor|major|critical"}], "summary": str}

A clean, correct answer scores 5 with empty issues. Do not invent problems; grade substance, not style."""


def _add_usage(dst: dict, src: dict | None):
    """Sum provider usage fields (both API shapes); accumulates across retries."""
    for k, v in (src or {}).items():
        if isinstance(v, int):
            dst[k] = dst.get(k, 0) + v


def chat(payload: dict, timeout: int = 420, usage: dict | None = None) -> str:
    global _temperature_dropped
    body = {"model": MODEL, "max_tokens": 2500, "temperature": 0.1, **payload}
    if API_STYLE == "anthropic":
        messages = payload.get("messages", [])
        sys_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        req = {"model": MODEL, "system": "".join(sys_msgs),
               "messages": [{"role": "user", "content": "".join(user_msgs)}],
               "max_tokens": 2500}
        if not _temperature_dropped:
            req["temperature"] = 0.1
        resp = requests.post(BASE, headers={
            "x-api-key": API_KEY, "anthropic-version": "2023-06-01",
            "content-type": "application/json", "user-agent": UA},
            json=req, timeout=timeout)
        if resp.status_code >= 400:
            detail = resp.text[:500]
            try:
                detail = (resp.json().get("error") or {}).get("message") or detail
            except ValueError:
                pass
            if not _temperature_dropped and "temperature" in detail.lower():
                _temperature_dropped = True
                log_progress({"step": "adapt", "ok": True,
                              "note": "model rejects temperature; dropped for rest of run"})
                return ""
            raise urllib.error.URLError(f"{resp.status_code} from {BASE}: {detail}")
        data = resp.json()
        if data.get("stop_reason") == "refusal":
            if usage is not None:
                _add_usage(usage, data.get("usage"))
            raise JudgeRefused(f"{MODEL} refused the prompt (stop_reason=refusal)")
        if usage is not None:
            _add_usage(usage, data.get("usage"))
        for b in data.get("content", []):
            if b.get("type") == "text":
                return b.get("text", "")
        return ""
    body = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, method="POST",
                                 headers={"content-type": "application/json", "user-agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
        if usage is not None:
            _add_usage(usage, data.get("usage"))
        return data["choices"][0]["message"]["content"]


def strict_json(text: str):
    s = text.strip()
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        return json.loads(s[i:j + 1])
    raise ValueError("no JSON: " + text[:200])


def log_progress(rec: dict):
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def flagged(v: dict) -> bool:
    if v.get("score", 5) <= 3:
        return True
    if v.get("overall_severity") in ("major", "critical"):
        return True
    return any(i.get("severity") in ("major", "critical") for i in v.get("issues", []))


def main():
    pools = []
    for line in open(POOLS, encoding="utf-8"):
        line = line.strip()
        if line:
            pools.append(json.loads(line))
    done = {}
    if VERDICTS.exists():
        for line in open(VERDICTS, encoding="utf-8"):
            try:
                r = json.loads(line)
                done[r["id"]] = r
            except (json.JSONDecodeError, KeyError):
                pass

    new_verdicts = []
    for p in pools:
        if STOP.exists():
            break
        pid = p["id"]
        if pid in done:
            continue
        prompt = ("## What was asked\n" + p["task"] +
                  "\n\n## The response under review\n" + p["answer"] +
                  "\n\nGrade the response now. Do NOT write any reasoning or explanation before or after it.\nReply with the strict JSON verdict object ONLY — one JSON object, no prose, no fences, no score 6-10.")
        verdict = None
        usage = {}
        refused = False
        for _ in range(8):
            try:
                raw = chat({"messages": [
                    {"role": "system", "content": RUBRIC},
                    {"role": "user", "content": prompt}]},
                    timeout=420, usage=usage)
                if not raw or not raw.strip():
                    time.sleep(5)
                    continue
                verdict = strict_json(raw)
                break
            except JudgeRefused:
                refused = True
                break
            except (ValueError, urllib.error.URLError) as e:
                time.sleep(5)
        if verdict is None:
            rec = {"step": "judge", "pair": pid, "ok": False}
            if refused:
                rec.update({"refused": True, "usage": usage})
            log_progress(rec)
            continue
        verdicts_rec = {"id": pid, "planted": p["planted"], "defect_class": p["defect_class"],
                        "defect_desc": p["defect_desc"], "judge": verdict,
                        "judge_model": MODEL, "usage": usage}
        new_verdicts.append(verdicts_rec)
        with open(VERDICTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(verdicts_rec, ensure_ascii=False) + "\n")
        log_progress({"step": "judge", "pair": pid, "ok": True, "score": verdict.get("score")})

    # scoring
    rows = []
    if VERDICTS.exists():
        for line in open(VERDICTS, encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    planted = [r for r in rows if r.get("planted")]
    clean = [r for r in rows if not r.get("planted")]
    caught = [r for r in planted if flagged(r["judge"])]
    ff = [r for r in clean if flagged(r["judge"])]
    lines = [
        f"# Side-Eye calibration baseline (judge: {JUDGE_ID})",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        f"Pairs: {len(rows)} total ({len(planted)} planted, {len(clean)} clean)",
        "",
        f"**Recall on planted defects: {len(caught)}/{len(planted)}"
        + ("" if planted else " (no planted pairs yet)")
        + "**"
        + f" — {100.0 * len(caught) / len(planted):.0f}%".replace("%", "") if planted else "",
        f"**False-flag rate on clean: {len(ff)}/{len(clean)}**" + (f" — {100.0 * len(ff) / len(clean):.0f}%" if clean else ""),
        "",
        "Per-pair:",
        "",
        "| id | planted | class | judge score | severity | flagged | truth |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        v = r["judge"]
        lines.append(
            f"| {r['id']} | {'yes' if r['planted'] else 'clean'} | {r.get('defect_class') or '-'} "
            f"| {v.get('score')} | {v.get('overall_severity')} | "
            f"{'YES' if flagged(v) else 'no'} | "
            f"{'CAUGHT' if (r['planted'] and flagged(v)) else ('FALSE-FLAG' if (not r['planted'] and flagged(v)) else 'ok')} |")
    if caught or ff:
        lines += ["", "Mismatches detail:"]
        for r in rows:
            v = r["judge"]
            if (r["planted"] and not flagged(v)) or (not r["planted"] and flagged(v)):
                lines.append(f"- {r['id']} (truth: {r['defect_desc'] or 'clean'}): {v.get('summary')}")
    lines.append("")
    lines.append("Re-run with a strong judge (fable-5) later for comparison: same pools, different judge — "
                 "that delta IS the metric (cheap-judge recall vs strong-judge recall).")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    log_progress({"step": "judge-done"})
    print(f"done: {len(rows)} pairs, recall {len(caught)}/{len(planted)}, false-flags {len(ff)}/{len(clean)}")


if __name__ == "__main__":
    main()
