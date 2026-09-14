#!/usr/bin/env python3
"""Emit calibration_review_sheet.md — the human re-label pass for the
un-audited clean pairs (pool contamination fix).

Reads calibration_pools.jsonl + both judges' outputs; selects the clean
pairs neither judge flagged (plus the Fable-refused clean pairs, which were
only half-judged). Re-run: python3 make_review_sheet.py
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "calibration_review_sheet.md"

from make_dashboard import AUDIT, REFUSED, flagged  # single source for the verified layer


def fence_for(text: str) -> str:
    """Longest backtick fence that won't collide with the content."""
    longest = 0
    for run in re.findall(r"`+", text):
        longest = max(longest, len(run))
    return "`" * max(3, longest + 1)


def main():
    pool = {}
    order = []
    for line in open(HERE / "calibration_pools.jsonl", encoding="utf-8"):
        p = json.loads(line)
        pool[p["id"]] = p
        order.append(p["id"])

    fab = {}
    for line in open(HERE / "fable-5_verdicts.jsonl", encoding="utf-8"):
        r = json.loads(line)
        fab[r["id"]] = r

    report = open(HERE / "qwen3.8_uncensored_4090_report.md", encoding="utf-8").read()
    qwen = {}
    for m in re.finditer(r"\| (cal-\d+-(?:clean|planted)|ctrl-\d+) \| (\w+) \| (\S+) \| (\d+) \| (\w+) \| (\w+) \|", report):
        pid, planted, cls, score, sev, fl = m.groups()
        qwen[pid] = {"score": int(score), "sev": sev, "flag": fl == "YES"}
    qwen_sum = {}
    for m in re.finditer(r"^- (cal-\d+-(?:clean|planted)|ctrl-\d+) \(truth: (.+?)\): (.+)$", report, re.M):
        qwen_sum[m.group(1)] = m.group(3).strip()

    # the audited 15 are done; the rest of the clean pool is this sheet
    unflagged, refused_clean = [], []
    for pid in order:
        p = pool[pid]
        if p["planted"] or pid in AUDIT:
            continue
        f = fab.get(pid, {}).get("judge")
        q = qwen.get(pid)
        if pid in REFUSED:
            refused_clean.append(pid)
        elif (f is not None and not flagged(f)) or f is None:
            if not (q and q["flag"]):
                unflagged.append(pid)

    print(f"sheet: {len(unflagged)} unflagged + {len(refused_clean)} fable-refused = "
          f"{len(unflagged) + len(refused_clean)} pairs")

    def pair_block(i: int, pid: str, why: str) -> str:
        p = pool[pid]
        f = fab.get(pid, {}).get("judge")
        q = qwen.get(pid)
        fline = ("**refused** (stop_reason=refusal) — " + REFUSED[pid]) if pid in REFUSED else (
            f"{f.get('score')}/{f.get('overall_severity')}"
            f"{' · flagged' if flagged(f) else ''} — {f.get('summary', '')}" if f else "unjudged")
        qline = (f"{q['score']}/{q['sev']}{' · flagged' if q['flag'] else ''} — {qwen_sum.get(pid, '')}"
                 if q else "unjudged")
        ans_fence = fence_for(p["answer"])
        return (
            f"## {i}. {pid}\n\n"
            f"- **topic:** {p['topic']}\n"
            f"- **task:** {p['task']}\n"
            f"- **context — {why}**\n"
            f"- **Qwen 27B said:** {qline}\n"
            f"- **Fable 5 said:** {fline}\n\n"
            f"- Verdict: [ ] CLEAN   [ ] DEFECT\n"
            f"  - if DEFECT → class: `incorrect_api_claim` / `unverified_claim` / `subtle_logic_bug` / `other: ____`\n"
            f"  - if DEFECT → one line (becomes the ground-truth `defect_desc`): ______\n\n"
            f"**Answer:**\n\n{ans_fence}\n{p['answer']}\n{ans_fence}\n\n---\n\n"
        )

    body = []
    i = 1
    for pid in unflagged:
        body.append(pair_block(i, pid, "neither judge flagged this pair"))
        i += 1
    if refused_clean:
        body.append(
            "\n### Fable refused these — 27B judged them clean, so they are only half-judged\n\n")
    for pid in refused_clean:
        body.append(pair_block(i, pid, "Fable refused; 27B scored it clean — a human eye is the only verdict on it"))
        i += 1

    out = f"""# Side-Eye calibration — clean-pool human re-label (pass 2)

**Why this exists.** The pool's {len([p for p in pool.values() if not p['planted']])} “clean” answers were
LLM-generated and never human-audited. The Fable calibration run flagged 15 of them;
a manual audit confirmed **all 15 are real latent defects** (44% contamination of the
clean pool). The {len(unflagged) + len(refused_clean)} pairs below are the remaining unaudited clean answers:
{len(unflagged)} that neither judge flagged, plus {len(refused_clean)} Fable refused (27B cleared — half-judged).
Until this pass is done, clean-side judge numbers are labels, not guarantees.

**How to do this (~20–30 min).** Read each ANSWER the way a senior reviewer would.
A DEFECT is any rubric-v3 issue:

1. **incorrect_api_claim** — the explanation states something false about the
   language/library API, *even if the code works*.
2. **unverified_claim** — a performance/behavior claim asserted as fact without
   basis (“guaranteed sub-microsecond”, “no additional round-trip”).
3. **subtle_logic_bug** — code that fails on real inputs: edge cases, empty
   inputs, type errors, snippets that don't compile.
4. **other** — anything else a senior reviewer would block on.

Mark one box per pair. If DEFECT, write the class + one line — that line becomes
the ground-truth `defect_desc` in the re-frozen pool.

**When done:** hand the marked sheet back. Labels go into a new
`calibration_pools_v2.jsonl` + a re-freeze commit; v1 stays untouched so the
frozen fable-5 run remains comparable. The 15 already-audited pairs are not on
this sheet — their findings live in `calibration-results.html` (the twist table)
and will be carried into v2.

{"".join(body)}
*Generated by make_review_sheet.py from calibration_pools.jsonl +
fable-5_verdicts.jsonl + qwen3.8_uncensored_4090_report.md. Regenerate:
`python3 make_review_sheet.py`.*
"""
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
