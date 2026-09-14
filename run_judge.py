#!/usr/bin/env python3
"""Run the Side-Eye judge over a JSONL of (prompt, answer) pairs.

Reads pairs (each: {"id", "prompt", "answer"}), grades each through the dogfood
Anthropic route (so judge spend is metered), and writes a verdicts JSONL plus a
one-screen summary. Optionally scores against a ground-truth file to measure
whether planted defects were caught without flagging clean answers.

Env: ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY (already set for the dogfood route).
Secrets come from env only — never hardcoded, never logged.

  python -m sideeye.run_judge --pairs sideeye/data/seed_pairs.jsonl \
      --ground-truth sideeye/data/ground_truth.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

# Make `sideeye` importable whether run as a module or a file.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sideeye.judge.judge import (  # noqa: E402
    DEFAULT_MODEL,
    judge,
    load_rubric,
    rubric_version,
)
from sideeye.judge.schema import is_flagged  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent
DEFAULT_RUBRIC = REPO / "rubric" / "rubric_v3.md"


def read_pairs(path):
    pairs = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            for field in ("id", "prompt", "answer"):
                if field not in obj:
                    raise ValueError(f"{path}:{lineno} missing field {field!r}")
            pairs.append(obj)
    return pairs


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Side-Eye judge runner (POC-0)")
    ap.add_argument("--pairs", required=True, help="input JSONL of (id, prompt, answer)")
    ap.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=None, help="verdicts JSONL (default: verdicts/verdicts-<ts>.jsonl)")
    ap.add_argument("--ground-truth", default=None, help="optional ground-truth JSON for planted-defect scoring")
    ap.add_argument("--base-url", default=os.environ.get("ANTHROPIC_BASE_URL"))
    args = ap.parse_args()

    base_url = args.base_url
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not base_url:
        fail("ANTHROPIC_BASE_URL not set (and --base-url not given)")
    if not api_key:
        fail("ANTHROPIC_API_KEY not set")

    rubric_path = pathlib.Path(args.rubric)
    if not rubric_path.exists():
        fail(f"rubric not found: {rubric_path}")
    rubric_text = load_rubric(rubric_path)
    rv = rubric_version(rubric_path)

    pairs = read_pairs(args.pairs)
    if not pairs:
        fail(f"no pairs in {args.pairs}")

    out_path = args.out
    if not out_path:
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = REPO / "verdicts"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"verdicts-{ts}.jsonl"
    out_path = pathlib.Path(out_path)

    verdicts = []
    total_in = total_out = 0
    total_cost = 0.0

    print(f"Judging {len(pairs)} pairs with {args.model} (rubric {rv})...\n")
    with open(out_path, "w", encoding="utf-8") as out:
        for p in pairs:
            try:
                verdict, meta = judge(
                    p["prompt"], p["answer"], rubric_text,
                    base_url=base_url, api_key=api_key, model=args.model,
                )
            except Exception as e:  # noqa: BLE001 — POC: log and continue
                print(f"  {p['id']}: JUDGE FAILED — {e}", file=sys.stderr)
                continue
            record = {
                "pair_id": p["id"],
                "rubric_version": rv,
                "judge_model": meta["judge_model"],
                **{k: verdict[k] for k in (
                    "answered_what_was_asked", "correctness", "claims_supported",
                    "score", "issues", "overall_severity", "summary",
                )},
                "input_tokens": meta["input_tokens"],
                "output_tokens": meta["output_tokens"],
                "cost_usd": meta["cost_usd"],
            }
            out.write(json.dumps(record) + "\n")
            verdicts.append(record)
            total_in += meta["input_tokens"]
            total_out += meta["output_tokens"]
            total_cost += meta["cost_usd"]

    _print_summary(verdicts, total_in, total_out, total_cost, out_path)
    if args.ground_truth:
        _score_ground_truth(verdicts, args.ground_truth)


def _print_summary(verdicts, total_in, total_out, total_cost, out_path):
    print(f"{'pair':<10} {'score':>5} {'correctness':<18} {'claims_ok':<9} "
          f"{'severity':<9} {'issues':>6}  summary")
    print("-" * 100)
    for v in verdicts:
        print(f"{v['pair_id']:<10} {v['score']:>5} {v['correctness']:<18} "
              f"{str(v['claims_supported']):<9} {v['overall_severity']:<9} "
              f"{len(v['issues']):>6}  {v['summary'][:44]}")
    print("-" * 100)
    print(f"verdicts: {len(verdicts)}   judge tokens: {total_in} in / {total_out} out   "
          f"judge cost: ${total_cost:.4f}")
    print(f"written to: {out_path}")


def _score_ground_truth(verdicts, gt_path):
    gt = json.loads(pathlib.Path(gt_path).read_text(encoding="utf-8"))
    by_id = {v["pair_id"]: v for v in verdicts}
    planted_caught = planted_total = 0
    clean_false_pos = clean_total = 0
    misses, false_positives = [], []

    for pid, info in gt.items():
        v = by_id.get(pid)
        if v is None:
            continue
        flagged = is_flagged(v)
        if info.get("planted"):
            planted_total += 1
            if flagged:
                planted_caught += 1
            else:
                misses.append((pid, info.get("defect_class", "?")))
        else:
            clean_total += 1
            if flagged:
                clean_false_pos += 1
                false_positives.append(pid)

    print("\n=== Objective planted-defect evaluation ===")
    print(f"planted defects caught: {planted_caught}/{planted_total}")
    print(f"clean answers wrongly flagged (false positives): {clean_false_pos}/{clean_total}")
    if misses:
        print("MISSED planted defects:")
        for pid, dc in misses:
            print(f"  - {pid} ({dc})")
    if false_positives:
        print(f"FALSE POSITIVES on clean answers: {false_positives}")
    verdict = "PASS" if planted_caught == planted_total and clean_false_pos == 0 else "REVIEW"
    print(f"objective result: {verdict}")


if __name__ == "__main__":
    main()
