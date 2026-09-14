#!/usr/bin/env python3
"""Re-judge the planted pairs the old rubric (v1) missed, using rubric v3.

Verifies the v3 rubric edit: "a wrong factual/API claim in the explanation is a
defect even if the code works." Compares old vs new verdicts per pair and
prints a table. Also re-judges the 5 planted pairs never judged at all (the
27B hiccuped at the end of the run).
"""
from __future__ import annotations

import json
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(HERE))
import evaluate  # reuse RUBRIC / chat / strict_json / flagged / log_progress


def old_flagged(v: dict) -> bool:
    return evaluate.flagged(v)


def main():
    pools = {}
    for line in open(HERE / "calibration_pools.jsonl", encoding="utf-8"):
        p = json.loads(line)
        pools[p["id"]] = p
    old = {}
    for line in open(HERE / "qwen3.8_uncensored_4090_verdicts.jsonl", encoding="utf-8"):
        r = json.loads(line)
        old[r["id"]] = r

    targets = []
    for pid, r in old.items():
        if r.get("planted") and not old_flagged(r["judge"]):
            targets.append(pid)
    # + the 5 planted pairs never judged
    for pid, p in pools.items():
        if p.get("planted") and pid not in old:
            targets.append(pid)

    print(f"Re-judging {len(targets)} missed planted pairs under rubric v3\n")
    rows = []
    out = []
    for pid in targets:
        p = pools[pid]
        prompt = ("## What was asked\n" + p["task"] +
                  "\n\n## The response under review\n" + p["answer"] +
                  "\n\nGrade the response now. Reply with the strict JSON verdict only.")
        verdict = None
        for _ in range(8):
            try:
                verdict = evaluate.strict_json(evaluate.chat({"messages": [
                    {"role": "system", "content": evaluate.RUBRIC},
                    {"role": "user", "content": prompt}]}, timeout=420))
                break
            except Exception as e:
                time.sleep(5)
        if verdict is None:
            print(f"  {pid}: JUDGE FAILED (8 retries)")
            continue
        was = old.get(pid, {}).get("judge")
        rows.append((pid, p.get("defect_class"),
                     (was or {}).get("score"), (was or {}).get("overall_severity"),
                     verdict.get("score"), verdict.get("overall_severity"),
                     old_flagged(verdict)))
        out.append({"id": pid, "planted": True, "defect_class": p.get("defect_class"),
                    "defect_desc": p.get("defect_desc"), "judge_v3": verdict,
                    "judge_model": evaluate.MODEL, "rubric": "rubric_v3"})
        print(f"  {pid}: {p.get('defect_class')}: score {rows[-1][2]} -> {rows[-1][4]}, "
              f"severity {rows[-1][3]} -> {rows[-1][5]}, flagged now: {rows[-1][6]}")

    with open(HERE / "rubric_v3_missed_verdicts.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    now_caught = sum(1 for r in rows if r[6])
    print(f"\nRESULT: {now_caught}/{len(rows)} previously-missed planted pairs now flagged")


if __name__ == "__main__":
    main()
