#!/usr/bin/env python3
"""Side-Eye sampler — the RANDOM stream (unbiased quality estimate).

Scans Codex rollout logs, treats a rollout as a completed session once it has
been idle for N minutes, and sends each new session's transcript to the judge
(Sonnet 5 by default) through the dogfood Anthropic route (so judge spend is
metered). Writes verdicts to verdicts/sampled.jsonl.

Idempotent: sessions already in the output file are skipped, so re-running is
safe. Fire-and-forget per session: a judge failure is retried once, then logged
and skipped — it never blocks. Reuses the Phase B judge module unchanged.

Env: ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY.

  python -m sideeye.sampler --idle-min 10 --sample-rate 1.0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sideeye.adapters import load_transcript, session_files  # noqa: E402
from sideeye.config import RouteError, require_judge_route  # noqa: E402
from sideeye.judge.judge import (  # noqa: E402
    DEFAULT_MODEL,
    judge_session,
    load_rubric,
    rubric_version,
)
from sideeye.record import session_verdict_record  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent
DEFAULT_RUBRIC = REPO / "rubric" / "rubric_session_v1.md"
DEFAULT_OUT = REPO / "verdicts" / "sampled.jsonl"


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def already_judged(out_path):
    seen = set()
    if out_path.exists():
        for line in open(out_path, encoding="utf-8"):
            line = line.strip()
            if line:
                seen.add(json.loads(line)["session_id"])
    return seen


def sampled_in(session_id, rate):
    """Deterministic per-session sampling so re-runs are stable."""
    if rate >= 1.0:
        return True
    h = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
    return (h % 10_000) < rate * 10_000


def main():
    ap = argparse.ArgumentParser(description="Side-Eye sampler (random stream)")
    ap.add_argument("--client", choices=("claude", "codex"), default="claude",
                    help="which client's sessions to sample (default claude)")
    ap.add_argument("--idle-min", type=float, default=10.0, help="minutes idle => session done")
    ap.add_argument("--sample-rate", type=float, default=1.0, help="0..1 (POC: 1.0)")
    ap.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    # Judge must hit the real Claude route (dogfood), never GLM — resolution
    # chain + cheap-route guards live in config.py.
    ap.add_argument("--base-url", default=None,
                    help="judge route override; default resolves from "
                         "SIDEEYE_JUDGE_* env, the sideeye config file, or ANTHROPIC_*")
    args = ap.parse_args()

    try:
        args.base_url, api_key, _route_source = require_judge_route(args.base_url)
    except RouteError as e:
        fail(str(e))

    rubric_text = load_rubric(args.rubric)
    rv = rubric_version(args.rubric)
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(exist_ok=True)
    seen = already_judged(out_path)

    cutoff = time.time() - args.idle_min * 60
    rollouts = session_files(args.client)
    done = [p for p in rollouts if p.stat().st_mtime < cutoff]

    print(f"{len(rollouts)} {args.client} sessions, {len(done)} idle>{args.idle_min}min, "
          f"{len(seen)} already judged. Judging new sessions...\n")

    judged = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for path in done:
            transcript = load_transcript(path)
            if transcript is None:
                continue
            sid = transcript["session_id"]
            if sid in seen or not sampled_in(sid, args.sample_rate):
                continue
            record = _judge_with_retry(transcript, rubric_text, rv, args, api_key)
            if record is None:
                continue
            out.write(json.dumps(record) + "\n")
            out.flush()
            seen.add(sid)
            judged += 1
            print(f"  {sid[:24]}  score={record['score']} {record['overall_severity']:<8} "
                  f"gen={record['generation_total_tokens']}tok  judge=${record['judge_cost_usd']:.4f}")

    print(f"\njudged {judged} new session(s) -> {out_path}")


def _judge_with_retry(transcript, rubric_text, rv, args, api_key):
    for attempt in (1, 2):
        try:
            verdict, meta = judge_session(
                transcript, rubric_text, base_url=args.base_url, api_key=api_key,
                model=args.model,
            )
            return session_verdict_record(
                transcript, verdict, meta, rubric_version=rv, source="sampled",
                tier=1, judged_at=int(time.time()),
            )
        except Exception as e:  # noqa: BLE001 — fire-and-forget, never block
            if attempt == 2:
                print(f"  {transcript['session_id'][:24]}: JUDGE FAILED after retry — {e}",
                      file=sys.stderr)
                return None
    return None


if __name__ == "__main__":
    main()
