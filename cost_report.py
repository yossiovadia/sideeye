#!/usr/bin/env python3
"""Side-Eye cost report — the money story for leadership.

Reads the RANDOM-sample verdict stream (verdicts/sampled.jsonl) and answers the
one question leadership cares about: *how much would this traffic have cost on an
expensive model, versus what it actually cost on the free model plus judging —
and did quality hold?*

The counterfactual is an ESTIMATE and is labeled as such: it prices the sessions'
actual generation tokens at an expensive model's rate. Actual generation cost is
$0 (GLM is free/internal). Savings = counterfactual − judge cost.

Escalated verdicts are shown SEPARATELY (defect discovery) and are NEVER pooled
into the savings/quality aggregate — they are an adversarial sample.

  python -m sideeye.cost_report --html sideeye/verdicts/cost-report.html
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sideeye.judge.judge import PRICING  # noqa: E402  (USD per token, per model)

REPO = pathlib.Path(__file__).resolve().parent
DEFAULT_SAMPLED = REPO / "verdicts" / "sampled.jsonl"
DEFAULT_ESCALATED = REPO / "verdicts" / "escalated.jsonl"
DEFAULT_COUNTERFACTUAL = "claude-sonnet-5"


def read_jsonl(path):
    path = pathlib.Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def counterfactual_cost(rec, model):
    """What this session's generation would have cost on `model`."""
    cin, cout = PRICING.get(model, PRICING[DEFAULT_COUNTERFACTUAL])
    return rec.get("generation_input_tokens", 0) * cin + rec.get("generation_output_tokens", 0) * cout


def summarize(sampled, counterfactual_model):
    # Partition by adapter_version: blind (v0, narrative-only) and sighted
    # (v1, code-aware) verdicts are NOT commensurable — a narrative-only score
    # and a code-aware score measure different things. Pooling them corrupts the
    # aggregate. Absence (pre-fix records) is treated as v0-blind. We report the
    # sighted aggregate as the headline; blind verdicts are shown as a separate
    # note so the user knows they exist and must not be mixed in.
    blind = [r for r in sampled if r.get("adapter_version", "v0-blind") == "v0-blind"]
    sighted = [r for r in sampled if r.get("adapter_version") == "v1-sighted"]
    cohort = sighted if sighted else sampled  # fall back to all if none sighted yet
    n = len(cohort)
    if n == 0:
        return None
    total_cf = sum(counterfactual_cost(r, counterfactual_model) for r in cohort)
    total_judge = sum(r.get("judge_cost_usd", 0.0) for r in cohort)
    total_gen_tokens = sum(r.get("generation_total_tokens", 0) for r in cohort)
    scores = [r["score"] for r in cohort if isinstance(r.get("score"), int)]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    major = sum(1 for r in cohort if r.get("overall_severity") in ("major", "critical"))
    return {
        "sessions": n,
        "counterfactual_model": counterfactual_model,
        "counterfactual_cost": total_cf,       # est. cost on the expensive model
        "actual_generation_cost": 0.0,         # GLM is free/internal
        "judge_cost": total_judge,             # real, metered
        "savings": total_cf - total_judge,
        "generation_tokens": total_gen_tokens,
        "avg_score": avg_score,
        "major_issue_rate": major / n,
        "adapter_version": "v1-sighted" if sighted else "v0-blind",
        "blind_excluded": len(blind) if sighted else 0,  # blind verdicts NOT in this aggregate
    }


def _fmt_usd(x):
    return f"${x:,.2f}" if abs(x) >= 0.005 else f"${x:.4f}"


def print_report(summary, escalated):
    if summary is None:
        print("No sampled sessions yet. Run some Codex-on-GLM sessions, then the "
              "sampler, then this report. (Escalations, if any, shown below.)")
    else:
        s = summary
        print("=" * 66)
        print("  SIDE-EYE COST REPORT  (random-sample stream)")
        print("=" * 66)
        print(f"  sessions judged            {s['sessions']}")
        print(f"  generation tokens          {s['generation_tokens']:,}")
        print(f"  avg quality score          {s['avg_score']:.2f} / 5")
        print(f"  major-issue rate           {s['major_issue_rate']*100:.0f}%")
        print("  " + "-" * 62)
        print(f"  Est. cost on {s['counterfactual_model']:<22} {_fmt_usd(s['counterfactual_cost'])}   (counterfactual)")
        print(f"  Actual generation (GLM, free)          {_fmt_usd(s['actual_generation_cost'])}")
        print(f"  Judge cost (metered)                   {_fmt_usd(s['judge_cost'])}")
        print("  " + "-" * 62)
        print(f"  ESTIMATED SAVINGS                      {_fmt_usd(s['savings'])}")
        print("=" * 66)
        if s.get("blind_excluded"):
            print(f"  ({s['blind_excluded']} blind-era verdicts excluded from this "
                  f"aggregate — adapter {s['adapter_version']}; not commensurable)")
    if escalated:
        print(f"\n  Escalations (separate stream, {len(escalated)} — defect discovery, "
              "not in the aggregate):")
        for r in escalated:
            print(f"    {r['session_id'][:20]}  score={r['score']} {r['overall_severity']:<8} "
                  f"{r['summary'][:50]}")


def render_html(summary, escalated, counterfactual_model):
    def esc(x):
        return html.escape(str(x))
    if summary is None:
        body = ("<p class='muted'>No sampled sessions yet — run Codex-on-GLM "
                "sessions, then the sampler, then regenerate this report.</p>")
        headline = "$—"
        sub = "awaiting live traffic"
    else:
        s = summary
        headline = _fmt_usd(s["savings"])
        sub = (f"across {s['sessions']} sessions · avg quality "
               f"{s['avg_score']:.2f}/5 · {s['major_issue_rate']*100:.0f}% major-issue rate")
        body = f"""
        <table>
          <tr><td>Est. cost on {esc(counterfactual_model)} <span class="est">(counterfactual)</span></td>
              <td class="num">{esc(_fmt_usd(s['counterfactual_cost']))}</td></tr>
          <tr><td>Actual generation — GLM (free/internal)</td>
              <td class="num">{esc(_fmt_usd(s['actual_generation_cost']))}</td></tr>
          <tr><td>Judge cost (metered)</td>
              <td class="num">{esc(_fmt_usd(s['judge_cost']))}</td></tr>
          <tr class="total"><td>Estimated savings</td>
              <td class="num">{esc(_fmt_usd(s['savings']))}</td></tr>
        </table>
        <p class="muted">Counterfactual prices the sessions' actual generation
        tokens ({s['generation_tokens']:,}) at {esc(counterfactual_model)} rates.
        It is an estimate of avoided spend, not a bill.</p>"""

    esc_rows = "".join(
        f"<tr><td>{esc(r['session_id'][:20])}</td><td class='num'>{esc(r['score'])}</td>"
        f"<td>{esc(r['overall_severity'])}</td><td>{esc(r['summary'])}</td></tr>"
        for r in escalated
    )
    esc_block = (f"<h2>Escalations <span class='muted'>(separate stream — defect "
                 f"discovery, not in the savings aggregate)</span></h2>"
                 f"<table><tr><th>session</th><th>score</th><th>severity</th><th>summary</th></tr>"
                 f"{esc_rows}</table>") if escalated else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Side-Eye Cost Report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
         max-width: 720px; margin: 40px auto; padding: 0 20px; }}
  .headline {{ font-size: 3rem; font-weight: 700; color: #0d7f72; }}
  .sub {{ color: #666; margin-bottom: 28px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  td, th {{ padding: 8px 12px; border-bottom: 1px solid #ccc; text-align: left; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .total td {{ font-weight: 700; border-top: 2px solid #333; }}
  .est, .muted {{ color: #888; font-size: 0.85em; font-weight: 400; }}
  h2 {{ font-size: 1.1rem; margin-top: 32px; }}
</style></head><body>
  <p class="muted">SIDE-EYE — draft cheap, review expensive</p>
  <div class="headline">{esc(headline)}</div>
  <div class="sub">estimated savings {esc(sub)}</div>
  {body}
  {esc_block}
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Side-Eye cost report")
    ap.add_argument("--sampled", default=str(DEFAULT_SAMPLED))
    ap.add_argument("--escalated", default=str(DEFAULT_ESCALATED))
    ap.add_argument("--counterfactual", default=DEFAULT_COUNTERFACTUAL,
                    help="expensive model to price against (default sonnet-5)")
    ap.add_argument("--html", default=None, help="also write an HTML report here")
    args = ap.parse_args()

    sampled = read_jsonl(args.sampled)
    escalated = read_jsonl(args.escalated)
    summary = summarize(sampled, args.counterfactual)
    print_report(summary, escalated)

    if args.html:
        out = pathlib.Path(args.html)
        out.parent.mkdir(exist_ok=True)
        out.write_text(render_html(summary, escalated, args.counterfactual), encoding="utf-8")
        print(f"\nHTML report: {out}")


if __name__ == "__main__":
    main()
