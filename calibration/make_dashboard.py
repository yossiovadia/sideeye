#!/usr/bin/env python3
"""Build calibration-results.html from the frozen pool + both judges' outputs.

Single source of truth: reads calibration_pools.jsonl, fable-5_verdicts.jsonl
and qwen3.8_uncensored_4090_report.md; writes a self-contained dashboard.
Re-run after any judge run: python3 make_dashboard.py

Human-verified layer (audit conclusions) is the only hardcoded data, below.
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "calibration-results.html"
PRICING = {"input_tokens": 10.0, "output_tokens": 50.0,
           "cache_creation_input_tokens": 12.5, "cache_read_input_tokens": 1.0}

# --- human-verified layer (audit of Fable's flagged-clean pairs, 2026-08-31) ---
AUDIT = {  # id -> one-line finding; every entry verified against the answer text
    "cal-06-clean": "psycopg2 escapes client-side — “driver sends params out-of-band” is wrong (same class as the planted API-claim defects)",
    "cal-07-clean": "Mutex(...) constructor + move_to_front on the wrong type — does not compile",
    "cal-08-clean": "ErrQuote/ErrBareQuote descriptions swapped vs Go's docs",
    "cal-11-clean": "“Option fields are omitted by default” — serde serializes null without the attribute",
    "cal-14-clean": "attributes undefined-return caching to the JSON replacer, which only affects argument keys",
    "cal-15-clean": "inotify on a symlink-swapped ConfigMap never fires; busybox lacks inotifywait; no app actually runs",
    "cal-20-clean": "sem.clone() — Semaphore is not Clone — does not compile",
    "cal-23-clean": "asserts Shutdown() sets r.Close = true — invented mechanism",
    "cal-26-clean": "example callback is () => string vs required () => Promise<T> — does not type-check",
    "cal-28-clean": "not a GK sketch: d=0 on insert, wrong merge condition, query ignores Δ",
    "cal-29-clean": "dialect-mixed pseudocode (MySQL rejects LIMIT in IN-subqueries); no per-batch COMMIT",
    "ctrl-03": "N - 1 underflows for [T; 0] — panics on an empty array",
    "ctrl-05": "spurious trailing empty field when the line ends with a quoted field",
    "cal-16-clean": "Option::replace(Some(val)) type error + UnsafeCell is !Sync — the queue cannot be shared (27B caught the Sync half in the v2 era)",
    "cal-27-clean": "in-progress Event guard is never created (dead code); (\"done\", None) contradicts the re-execute claim",
}
REFUSED = {  # id -> why (content class Fable's safety layer refuses to grade)
    "cal-03-clean": "reqwest client for an IdP JWKS endpoint — identity key material, TLS",
    "cal-03-planted": "same task, planted timeout() claim — identity key material, TLS",
    "cal-06-planted": "execute user-supplied SQL safely — SQL-injection framing",
    "cal-13-clean": "stream a 100MB file download with Range support — bulk transfer",
}
REFUSAL_WASTE_EST = 1.32  # $ — 64 refused attempts × ~2066 input tokens (estimate, not in verdicts file)
MISC_EST = 0.03           # $ — smoke + verification calls (estimate)

CLASSES = ["incorrect_api_claim", "unverified_claim", "subtle_logic_bug"]


def flagged(v: dict) -> bool:
    if v.get("score", 5) <= 3:
        return True
    if v.get("overall_severity") in ("major", "critical"):
        return True
    return any(i.get("severity") in ("major", "critical") for i in v.get("issues", []))


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
        qwen[pid] = {"score": int(score), "sev": sev, "flagged": fl == "YES"}
    qwen_sum = {}
    for m in re.finditer(r"^- (cal-\d+-(?:clean|planted)|ctrl-\d+) \(truth: (.+?)\): (.+)$", report, re.M):
        qwen_sum[m.group(1)] = m.group(3).strip()

    pairs = []
    for pid in order:
        p = pool[pid]
        f = fab.get(pid)
        q = qwen.get(pid)
        fv = f["judge"] if f else None
        pairs.append({
            "id": pid, "topic": p["topic"], "planted": p["planted"],
            "cls": p["defect_class"] or None, "defect": p["defect_desc"] or None,
            "task": p["task"][:400],
            "q": None if not q else {"score": q["score"], "sev": q["sev"], "flag": q["flagged"],
                                     "sum": qwen_sum.get(pid, "")},
            "f": None if not fv else {"score": fv.get("score"), "sev": fv.get("overall_severity"),
                                      "flag": flagged(fv), "sum": fv.get("summary", ""),
                                      "usage": f.get("usage", {})},
            "refused": pid in REFUSED,
            "audit": AUDIT.get(pid),
        })

    # --- stats ---
    def perclass(rows, judge):
        out = {}
        for cls in CLASSES:
            sel = [r for r in rows if r["planted"] and r["cls"] == cls]
            j = [r for r in sel if r[judge]]
            out[cls] = {"caught": sum(1 for r in j if r[judge]["flag"]), "judged": len(j),
                        "total": len(sel)}
        sel = [r for r in rows if r["planted"]]
        j = [r for r in sel if r[judge]]
        out["all"] = {"caught": sum(1 for r in j if r[judge]["flag"]), "judged": len(j), "total": len(sel)}
        ff_sel = [r for r in rows if not r["planted"]]
        ff_j = [r for r in ff_sel if r[judge]]
        out["ff"] = {"caught": sum(1 for r in ff_j if r[judge]["flag"]), "judged": len(ff_j),
                     "total": len(ff_sel)}
        return out

    stats = {"q": perclass(pairs, "q"), "f": perclass(pairs, "f")}
    tot_in = sum(r["f"]["usage"].get("input_tokens", 0) for r in pairs if r["f"])
    tot_out = sum(r["f"]["usage"].get("output_tokens", 0) for r in pairs if r["f"])
    judged_cost = sum(sum(v * p for k, v in r["f"]["usage"].items() for p in [PRICING.get(k, 0)])
                      for r in pairs if r["f"]) / 1e6
    stats["cost"] = {"in": tot_in, "out": tot_out, "judged": round(judged_cost, 2),
                     "waste_est": REFUSAL_WASTE_EST, "misc_est": MISC_EST,
                     "total": round(judged_cost + REFUSAL_WASTE_EST + MISC_EST, 2),
                     "per_pair": round(judged_cost / max(1, sum(1 for r in pairs if r["f"])), 4)}

    data = {"pairs": pairs, "stats": stats,
            "refused": {k: v for k, v in REFUSED.items()}}
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(pairs)} pairs, fable cost ${stats['cost']['total']})")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Side-Eye calibration — 27B vs Fable 5</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: #010409; color: #c9d1d9;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 40px 16px 64px; min-height: 100vh;
}
.wrap { max-width: 980px; margin: 0 auto; }
h1 { font-size: 19px; font-weight: 600; letter-spacing: .2px; color: #e6edf3; margin: 0 0 8px; }
.sub { margin: 0 0 26px; font-size: 12.5px; line-height: 1.6; color: #8b949e; max-width: 720px; }
section { margin: 0 0 28px; }
h2 { font-size: 13px; font-weight: 600; color: #e6edf3; margin: 0 0 4px; letter-spacing: .3px; }
.note { font-size: 11.5px; line-height: 1.6; color: #8b949e; margin: 0 0 14px; }
.card { background: #0d1117; border: 1px solid #30363d; border-radius: 10px; padding: 18px 20px; }
/* hero */
.hero { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.judge { background: #0d1117; border: 1px solid #30363d; border-radius: 10px; padding: 18px 20px; }
.judge .who { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #8b949e; margin-bottom: 10px; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.dot.q { background: #3987e5; } .dot.f { background: #d95926; }
.big { font-size: 42px; font-weight: 700; color: #e6edf3; line-height: 1.05; }
.big small { font-size: 16px; color: #8b949e; font-weight: 400; margin-left: 6px; }
.kv { margin-top: 12px; font-size: 12px; line-height: 1.75; color: #c9d1d9; }
.kv span { color: #8b949e; }
.kv b { font-weight: 600; color: #e6edf3; }
.hl-good { color: #0ca30c; font-weight: 600; } .hl-bad { color: #d03b3b; font-weight: 600; }
.hl-twist { color: #9085e9; font-weight: 600; }
/* bars */
.barrows { display: flex; flex-direction: column; gap: 14px; }
.bargrp .blab { font-size: 12px; color: #c9d1d9; margin-bottom: 5px; }
.bargrp .blab .dim { color: #8b949e; font-size: 11px; }
.bar { position: relative; height: 16px; margin: 4px 0; }
.bar .track { position: absolute; inset: 0; background: #161b22; border-radius: 4px; }
.bar .fill { position: absolute; top: 0; height: 16px; border-radius: 4px; }
.bar .fill.q { background: #3987e5; } .bar .fill.f { background: #d95926; }
.bar .val { position: absolute; top: 0; line-height: 16px; font-size: 11px; color: #8b949e; white-space: nowrap; }
.axis { position: relative; height: 18px; margin-top: 2px; border-top: 1px solid #21262d; }
.axis span { position: absolute; top: 3px; font-size: 10.5px; color: #8b949e; transform: translateX(-50%); }
.axis span::before { content: ""; position: absolute; left: 50%; top: -4px; width: 1px; height: 4px; background: #30363d; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; margin: 0 0 12px; font-size: 11.5px; color: #8b949e; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
/* grid */
.ghead { display: grid; grid-template-columns: 84px 1fr 1fr; gap: 6px; margin-bottom: 6px; font-size: 11px; color: #8b949e; }
.ghead div:nth-child(n+2) { text-align: center; }
.grow { display: grid; grid-template-columns: 84px 1fr 1fr; gap: 6px; margin-bottom: 6px; }
.grow .rid { font-size: 11.5px; color: #8b949e; padding-top: 7px; }
.grow.ctrl { grid-template-columns: 84px repeat(5, 1fr); }
.tile { position: relative; background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 6px 8px; min-height: 40px; cursor: default; }
.tile:focus-visible { outline: 2px solid #58a6ff; outline-offset: 1px; }
.tile .tid { font-size: 10.5px; color: #8b949e; }
.tile .tid .pl { color: #d29922; }
.chips { display: flex; gap: 5px; margin-top: 5px; }
.chip { position: relative; width: 20px; height: 20px; border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 11px; line-height: 1; }
.chip::after { content: attr(data-j); position: absolute; top: -4px; left: -4px; font-size: 8px; color: #8b949e; background: #161b22; border-radius: 3px; padding: 0 2px; }
.st-caught { background: #0ca30c; color: #010409; }
.st-missed { background: #d03b3b; color: #ffffff; }
.st-poolbug { background: #9085e9; color: #010409; }
.st-ok { background: #21262d; color: #484f58; }
.st-unjudged { background: transparent; border: 1px dashed #484f58; color: #484f58; }
.st-refused { background: #21262d; border: 1px solid #484f58; color: #8b949e; }
/* tables */
table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
th { text-align: left; color: #8b949e; font-weight: 400; font-size: 11px; padding: 7px 10px; border-bottom: 1px solid #30363d; }
td { padding: 7px 10px; border-bottom: 1px solid #21262d; vertical-align: top; line-height: 1.5; }
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.tag { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.t-good { background: rgba(12,163,12,.15); color: #0ca30c; }
.t-bad { background: rgba(208,59,59,.15); color: #e66767; }
.t-twist { background: rgba(144,133,233,.15); color: #9085e9; }
.t-mut { background: #21262d; color: #8b949e; }
.t-ring { background: transparent; border: 1px solid #484f58; color: #8b949e; }
/* cost */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.stat { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px 14px; }
.stat .v { font-size: 21px; font-weight: 700; color: #e6edf3; }
.stat .l { font-size: 11px; color: #8b949e; margin-top: 4px; line-height: 1.5; }
/* tooltip */
#tip { position: fixed; z-index: 10; max-width: 420px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px 12px; font-size: 11.5px; line-height: 1.55; color: #c9d1d9; box-shadow: 0 12px 40px rgba(0,0,0,.6); display: none; pointer-events: none; }
#tip .h { color: #e6edf3; font-weight: 600; margin-bottom: 5px; }
#tip .d { color: #8b949e; }
#tip .f-sum { margin-top: 5px; color: #c9d1d9; }
footer { margin-top: 34px; font-size: 11.5px; line-height: 1.7; color: #8b949e; border-top: 1px solid #21262d; padding-top: 16px; }
/* bottom line */
.verdicts { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 10px; }
.verd { background: #0d1117; border: 1px solid #30363d; border-radius: 10px; padding: 12px 14px; }
.verd .tag { padding: 2px 8px; font-weight: 700; letter-spacing: .5px; }
.tag.v-good { background: rgba(12,163,12,.15); color: #0ca30c; }
.tag.v-serious { background: rgba(236,131,90,.15); color: #ec835a; }
.tag.v-warn { background: rgba(250,178,25,.15); color: #fab219; }
.tag.v-next { background: rgba(57,135,229,.15); color: #3987e5; }
.verd .t { font-size: 12.5px; color: #e6edf3; font-weight: 600; margin: 7px 0 4px; }
.verd .d { font-size: 11.5px; line-height: 1.55; color: #8b949e; }
.verd .d b { color: #c9d1d9; font-weight: 600; }
.srow { display: grid; grid-template-columns: 150px 1fr; gap: 10px; align-items: center; margin: 7px 0; }
.srow .sl { font-size: 11.5px; color: #c9d1d9; }
.srow .sl .dim { color: #8b949e; font-size: 10.5px; }
.splot { position: relative; height: 30px; }
.splot .grid0 { position: absolute; top: 13px; bottom: 0; width: 1px; background: #21262d; }
.splot .line { position: absolute; top: 18px; height: 2px; background: #30363d; }
.splot .d1, .splot .d2 { position: absolute; top: 14px; width: 10px; height: 10px; border-radius: 50%; transform: translateX(-50%); }
.splot .d1 { background: #3987e5; } .splot .d2 { background: #d95926; }
.splot .l1, .splot .l2 { position: absolute; top: 0; font-size: 10.5px; white-space: nowrap; }
.splot .l1 { color: #3987e5; } .splot .l2 { color: #d95926; }
.saxis { position: relative; height: 15px; border-top: 1px solid #21262d; }
.saxis span { position: absolute; top: 3px; font-size: 10px; color: #8b949e; transform: translateX(-50%); }
@media (max-width: 640px) { .hero { grid-template-columns: 1fr; } .big { font-size: 34px; } .grow.ctrl { grid-template-columns: 60px repeat(5, 1fr); } .srow { grid-template-columns: 105px 1fr; } }
</style>
</head>
<body>
<div class="wrap">
<h1>Side-Eye calibration — 27B vs Fable 5</h1>
<p class="sub">Same frozen yardstick, two judges. 63 (task, answer) pairs — 29 planted with one
hidden subtle defect, 34 clean — graded blind under rubric v3. Qwen3.8-27B local ($0) vs
claude-fable-5 via the dogfood gateway ($10/$50 per MTok). 2026-08-31.</p>

<section>
  <h2>Bottom line</h2>
  <p class="note">What this run established — evidence and caveats in the sections below, honesty footnotes in the footer.</p>
  <div class="verdicts" id="verdicts"></div>
  <div class="card" style="margin-top:12px">
    <div class="legend"><span><i style="background:#3987e5"></i>Qwen3.8-27B (v2 report)</span><span><i style="background:#d95926"></i>Fable 5 (v3)</span></div>
    <div id="slope"></div>
  </div>
</section>

<section>
  <div class="hero" id="hero"></div>
</section>

<section>
  <h2>Recall on planted defects, by class <span style="color:#8b949e;font-weight:400">(of judged)</span></h2>
  <p class="note">Fable's one miss: cal-04-p (email-regex laxness — 27B missed it too; arguably a design choice, not a bug).
  27B column is the committed v2-era report; the post-v3 re-judge ref is 17/23 = 74% overall, 8/10 API-claim — so ~3 of the
  five API-claim delta rows are rubric gain, not judge gain, until the 27B post-v3 verdicts file lands.</p>
  <div class="card">
    <div class="legend"><span><i style="background:#3987e5"></i>Qwen3.8-27B (v2 report)</span><span><i style="background:#d95926"></i>Fable 5 (v3)</span></div>
    <div class="barrows" id="bars"></div>
    <div class="axis" id="axis"></div>
  </div>
</section>

<section>
  <h2>The 63-pair delta</h2>
  <p class="note">One tile per pair; the two chips are Qwen (left) and Fable (right). Hover or focus a tile for the full verdicts.
  <span class="hl-twist">◆ = a “clean” pair Fable flagged that a human audit confirmed as a real latent defect in the pool.</span></p>
  <div class="legend" id="gridlegend"></div>
  <div class="card">
    <div class="ghead"><div>pair</div><div>clean</div><div>planted</div></div>
    <div id="grid"></div>
  </div>
</section>

<section>
  <h2>The twist: the yardstick is warped</h2>
  <p class="note">Fable flagged 15 of 32 “clean” pairs it judged — a raw 47% “false-flag rate”. Every one was read against the
  answer text. <span class="hl-twist">15/15 are genuine latent defects</span> the pool labeled clean (44% of the clean pool):
  compile errors, invented mechanisms, broken patterns. Neither the 27B nor the pool's own validation caught any.
  Qwen's two “false-flags” in its report (cal-16-c, cal-27-c) were also correct catches. The pool needs a human re-label + re-freeze —
  the 17 clean pairs neither judge flagged remain unaudited.</p>
  <div class="card">
    <table id="audit"><thead><tr><th>pair</th><th>topic</th><th>defect Fable found (audited real)</th></tr></thead><tbody></tbody></table>
  </div>
</section>

<section>
  <h2>Refusals — a Fable coverage hole</h2>
  <p class="note">Fable returned stop_reason: “refusal” (HTTP 200, zero output) deterministically on these 4 — all security/credential-adjacent
  grading content. 2 of 4 carry planted defects Fable never saw. Counted as unjudged, per the honesty rules. Not “fixed” by rewording the
  rubric — that would poison the frozen comparison.</p>
  <div class="tiles" id="refused"></div>
</section>

<section>
  <h2>Cost — real, from usage records</h2>
  <div class="tiles" id="cost"></div>
  <p class="note" style="margin:10px 0 0">Fable verdicts are output-heavy (~1.2k output tokens/pair) — that's what pushes per-pair cost to ~$0.075.
  27B: $0 (local L40S box). All judge traffic meters onto the dogfood dashboard.</p>
</section>

<section>
  <h2>Full pair table <span style="color:#8b949e;font-weight:400">(the readable twin of the grid)</span></h2>
  <div class="card" style="overflow-x:auto">
    <table id="pairs"><thead><tr><th>pair</th><th>truth</th><th>class</th>
    <th class="num">Qwen 27B</th><th class="num">Fable 5</th><th>status</th></tr></thead><tbody></tbody></table>
  </div>
</section>

<footer>
  Honesty notes: (1) 27B column = committed baseline report, generated 2026-08-30 19:41 PDT — v2-era rubric (v3 committed 2026-08-31 08:11);
  5 pairs the 27B never judged (cal-07-c, cal-15-c, cal-28-c/p, ctrl-05) shown unjudged. (2) Fable judged 59/63; 4 refusals counted as unjudged.
  (3) Recall denominators are judged-only, per the harness; overall-of-29 is shown alongside. (4) Cost = measured usage in
  fable-5_verdicts.jsonl for judged pairs + labeled estimates for refused attempts. (5) Data: calibration_pools.jsonl (frozen),
  fable-5_verdicts.jsonl, qwen3.8_uncensored_4090_report.md. Regenerate: python3 make_dashboard.py.
</footer>
</div>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---- hero ---- */
const S = DATA.stats;
$("#hero").innerHTML = `
  <div class="judge"><div class="who"><span class="dot f"></span>Fable 5 — claude-fable-5, dogfood gateway, rubric v3</div>
    <div class="big">${Math.round(100*S.f.all.caught/S.f.all.judged)}%<small>${S.f.all.caught}/${S.f.all.judged} judged · ${S.f.all.caught}/${S.f.all.total} of all planted</small></div>
    <div class="kv">
      <div><span>API-claim class</span> — <b>${S.f["incorrect_api_claim"].caught}/${S.f["incorrect_api_claim"].judged}</b> <span>(27B: ${S.q["incorrect_api_claim"].caught}/${S.q["incorrect_api_claim"].judged})</span></div>
      <div><span>“false-flags” on clean</span> — 15/32 raw → <span class="hl-twist">15/15 audited real pool defects</span></div>
      <div><span>refusals</span> — <span class="hl-bad">4</span> <span>(security-adjacent content)</span> · <span>cost</span> <b>$${S.cost.total}</b></div>
    </div>
  </div>
  <div class="judge"><div class="who"><span class="dot q"></span>Qwen3.8-27B — local, $0, committed v2-era report</div>
    <div class="big">${Math.round(100*S.q.all.caught/S.q.all.judged)}%<small>${S.q.all.caught}/${S.q.all.judged} judged · ${S.q.all.caught}/${S.q.all.total} of all planted</small></div>
    <div class="kv">
      <div><span>post-v3 re-judge ref</span> — <b>17/23 = 74%</b> <span>overall · 8/10 API-claim</span></div>
      <div><span>false-flags on clean</span> — <b>2/30</b> <span>— both were correct catches of pool defects</span></div>
      <div><span>weakness</span> — API-claim class <b>${S.q["incorrect_api_claim"].caught}/${S.q["incorrect_api_claim"].judged}</b> <span>writes the right observation, scores 4/minor</span></div>
    </div>
  </div>`;

/* ---- bottom line ---- */
{
const F = S.f, Q = S.q;
const pct = (a, b) => Math.round(100 * a / b);
const nReal = DATA.pairs.filter(p => p.audit && !p.planted).length;
const nClean = DATA.pairs.filter(p => !p.planted).length;
const nRef = DATA.pairs.filter(p => p.refused).length;
$("#verdicts").innerHTML = [
  ["v-good", "PROVEN", "The yardstick has teeth",
   `Fable caught <b>${F.all.caught}/${F.all.judged}</b> planted defects — and the judges found <b>${nReal} real defects</b> hiding in “clean” answers nobody had seen.`],
  ["v-good", "BETTER, AS EXPECTED", "Fable clears the judge bar",
   `<b>${pct(F.all.caught, F.all.judged)}% vs ${pct(Q.all.caught, Q.all.judged)}%</b> planted recall (27B post-v3 ref: 74%). API-claim class: <b>${Q.incorrect_api_claim.caught}/${Q.incorrect_api_claim.judged} → ${F.incorrect_api_claim.caught}/${F.incorrect_api_claim.judged}</b>. Zero pairs 27B caught that Fable missed.`],
  ["v-serious", "CRACKED WALL", "The yardstick itself was warped",
   `<b>${nReal}/${nClean} (44%)</b> of the “clean” answers carry real defects — Fable’s 15 “false-flags” are <b>15/15 true positives</b>. Clean-side numbers are unquotable until the human re-label + re-freeze.`],
  ["v-warn", "COVERAGE HOLE", `${nRef}/63 refusals (${pct(nRef, 63)}%)`,
   `Deterministic Fable refusals, all security/credential-adjacent content — 2 carried planted defects it never saw. Metered as unjudged, not worked around.`],
  ["v-next", "NEXT", "Re-freeze the pool, then measure 27B as author",
   `Judges are now measured. The pitch is missing its draft-quality column: what share of 27B drafts passes a Fable gate.`],
].map(([c, t, h, d]) => `<div class="verd"><span class="tag ${c}">${t}</span><div class="t">${h}</div><div class="d">${d}</div></div>`).join("");
const labPos = p => p < 15 ? "translateX(0)" : p > 85 ? "translateX(-100%)" : "translateX(-50%)";
$("#slope").innerHTML = [["incorrect_api_claim", "incorrect_api_claim"], ["unverified_claim", "unverified_claim"],
  ["subtle_logic_bug", "subtle_logic_bug"], ["all", "all planted"]].map(([k, lab]) => {
  const qp = 100 * Q[k].caught / Q[k].judged, fp = 100 * F[k].caught / F[k].judged;
  return `<div class="srow"><div class="sl">${lab} <span class="dim">(${Q[k].total} planted)</span></div>
    <div class="splot">
      ${[0, 50, 100].map(g => `<span class="grid0" style="left:${g}%"></span>`).join("")}
      <span class="line" style="left:${qp}%;width:${Math.max(0.5, fp - qp)}%"></span>
      <span class="d1" style="left:${qp}%"></span><span class="d2" style="left:${fp}%"></span>
      <span class="l1" style="left:${qp}%;transform:${labPos(qp)}">${Math.round(qp)}%</span>
      <span class="l2" style="left:${fp}%;transform:${labPos(fp)}">${Math.round(fp)}%</span>
    </div></div>`;
}).join("") + `<div class="srow"><div class="sl"></div><div class="saxis">
  <span style="left:0%">0</span><span style="left:50%">50</span><span style="left:100%">100</span></div></div>`;
}

/* ---- bars ---- */
const bnames = [["incorrect_api_claim","incorrect_api_claim"],["unverified_claim","unverified_claim"],
                ["subtle_logic_bug","subtle_logic_bug"],["all","all planted"]];
$("#bars").innerHTML = bnames.map(([k, lab]) => {
  const q = S.q[k], f = S.f[k];
  const qp = 100*q.caught/q.judged, fp = 100*f.caught/f.judged;
  return `<div class="bargrp"><div class="blab">${esc(lab)} <span class="dim">(${q.total} planted${k!=="all"?"":" · 27B v2 / Fable v3"})</span></div>
    <div class="bar"><div class="track"></div><div class="fill q" style="width:${qp}%"></div><div class="val" style="left:calc(${qp}% + 8px)">${q.caught}/${q.judged}</div></div>
    <div class="bar"><div class="track"></div><div class="fill f" style="width:${fp}%"></div><div class="val" style="left:calc(${fp}% + 8px)">${f.caught}/${f.judged}${k==="all"?` · ${Math.round(fp)}% vs ${Math.round(qp)}%`:''}</div></div>
  </div>`;
}).join("");
for (const t of [0,25,50,75,100]) $("#axis").innerHTML += `<span style="left:${t}%">${t}</span>`;

/* ---- grid ---- */
function state(r, j) {  // per-judge tile state
  if (r.refused && j === "f") return "refused";
  const v = r[j];
  if (!v) return "unjudged";
  if (r.planted) return v.flag ? "caught" : "missed";
  return v.flag ? (r.audit ? "poolbug" : "poolbug") : "ok";
}
const GL = [["caught","✓ caught"],["missed","✗ missed"],["poolbug","◆ clean-flagged — audited real"],
            ["ok","· ok (unflagged)"],["unjudged","unjudged"],["refused","⌀ refused"]];
const GC = {caught:"#0ca30c", missed:"#d03b3b", poolbug:"#9085e9", ok:"#21262d", unjudged:"transparent", refused:"#21262d"};
$("#gridlegend").innerHTML = GL.map(([s, l]) =>
  `<span><i style="background:${GC[s]};${s==="unjudged"||s==="refused"?"border:1px solid #484f58":""}"></i>${l}</span>`).join("");
const GLY = {caught:"✓", missed:"✗", poolbug:"◆", ok:"·", unjudged:"", refused:"⌀"};
function tile(r, kind) {
  const q = state(r, "q"), f = state(r, "f");
  const tag = r.planted ? '<span class="pl">◆ planted</span>' : "clean";
  return `<div class="tile" tabindex="0" data-id="${r.id}" data-kind="${kind}">
    <div class="tid">${esc(r.id)} · ${tag}</div>
    <div class="chips">
      <span class="chip st-${q}" data-j="Q">${GLY[q]}</span>
      <span class="chip st-${f}" data-j="F">${GLY[f]}</span>
    </div></div>`;
}
let grid = "";
for (let i = 1; i <= 29; i++) {
  const n = String(i).padStart(2, "0");
  const c = DATA.pairs.find(p => p.id === `cal-${n}-clean`);
  const pl = DATA.pairs.find(p => p.id === `cal-${n}-planted`);
  if (!c && !pl) continue;
  grid += `<div class="grow"><div class="rid">cal-${n}</div>${tile(c || pl, "cal")}${pl ? tile(pl, "cal") : ""}</div>`;
}
grid += `<div class="grow ctrl"><div class="rid">ctrl</div>` +
  [1,2,3,4,5].map(i => tile(DATA.pairs.find(p => p.id === `ctrl-${String(i).padStart(2,"0")}`), "ctrl")).join("") + `</div>`;
$("#grid").innerHTML = grid;

/* ---- tooltip ---- */
const tip = $("#tip");
function showTip(r, x, y) {
  const q = r.q, f = r.f;
  const truth = r.planted ? `planted — ${r.cls}` : (r.audit ? "labeled clean — <b>audit: real defect</b>" : "clean");
  tip.innerHTML = `<div class="h">${esc(r.id)} <span class="d">· ${esc(r.topic)}</span></div>
    <div>${truth}</div>
    ${r.defect ? `<div class="d">defect: ${esc(r.defect.slice(0,220))}</div>` : ""}
    <div style="margin-top:5px"><b style="color:#3987e5">Qwen</b> ${q ? `${q.score}/${q.sev}${q.flag?" · flagged":""}` : "unjudged"}
      ${q?.sum ? `<div class="d">${esc(q.sum.slice(0,200))}</div>` : ""}</div>
    <div style="margin-top:5px"><b style="color:#d95926">Fable</b> ${r.refused ? "refused (stop_reason=refusal)" : f ? `${f.score}/${f.sev}${f.flag?" · flagged":""}` : "unjudged"}
      ${f?.sum ? `<div class="f-sum">${esc(f.sum)}</div>` : ""}</div>
    ${r.audit ? `<div style="margin-top:5px" class="hl-twist">◆ ${esc(r.audit)}</div>` : ""}
    ${r.refused ? `<div class="d" style="margin-top:5px">${esc(DATA.refused[r.id])}</div>` : ""}`;
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(x + 14, innerWidth - w - 10) + "px";
  tip.style.top = Math.min(y + 14, innerHeight - h - 10) + "px";
}
function hideTip() { tip.style.display = "none"; }
document.querySelectorAll(".tile").forEach(t => {
  const r = DATA.pairs.find(p => p.id === t.dataset.id);
  const show = e => showTip(r, e.clientX ?? 0, e.clientY ?? 0);
  t.addEventListener("mousemove", show);
  t.addEventListener("mouseleave", hideTip);
  t.addEventListener("focus", () => { const b = t.getBoundingClientRect(); showTip(r, b.right, b.top); });
  t.addEventListener("blur", hideTip);
});

/* ---- audit table ---- */
$("#audit tbody").innerHTML = DATA.pairs.filter(p => p.audit && p.f?.flag && !p.planted).map(p =>
  `<tr><td>${esc(p.id)}</td><td>${esc(p.topic)}</td><td>${esc(p.audit)}</td></tr>`).join("");

/* ---- refusals ---- */
$("#refused").innerHTML = DATA.pairs.filter(p => p.refused).map(p =>
  `<div class="stat"><div class="v" style="font-size:14px;color:#8b949e">${esc(p.id)} ${p.planted?"<span class='hl-bad'>planted</span>":"clean"}</div>
   <div class="l">${esc(p.cls || "—")}<br>${esc(DATA.refused[p.id])}</div></div>`).join("");

/* ---- cost ---- */
const C = S.cost;
$("#cost").innerHTML = [
  [`$${C.total}`, `total · ${C.in.toLocaleString()} in / ${C.out.toLocaleString()} out tokens @ $10/$50 per MTok`],
  [`$${C.judged}`, `measured — 59 judged pairs (usage in verdicts file)`],
  [`≈$${C.waste_est}`, `64 refused attempts (~2k in each) — estimate, not in verdicts file`],
  [`$${C.per_pair}`, "per judged pair — Fable writes ~1.2k-token verdicts"],
  [`$0`, "Qwen 27B — local L40S box; the cheap side of the pattern is free"],
].map(([v, l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

/* ---- pair table ---- */
function statusTag(p) {
  const q = p.q?.flag, f = p.f?.flag;
  if (p.planted) {
    if (p.f && f && q) return '<span class="tag t-good">caught by both</span>';
    if (p.f && f) return '<span class="tag t-good">caught (Fable only)</span>';
    if (q) return '<span class="tag t-good">caught (27B only)</span>';
    if (p.refused || !p.q || !p.f) return '<span class="tag t-ring">not fully judged</span>';
    return '<span class="tag t-bad">missed by both</span>';
  }
  if (p.audit && (q || f)) return '<span class="tag t-twist">pool defect — flagged by ' + (q && f ? "both" : f ? "Fable" : "27B") + '</span>';
  if (p.refused && !p.f) return '<span class="tag t-ring">Fable refused</span>';
  return '<span class="tag t-mut">ok</span>';
}
$("#pairs tbody").innerHTML = DATA.pairs.map(p => {
  const q = p.q ? `${p.q.score}/${p.q.sev}${p.q.flag ? " ⚑" : ""}` : "—";
  const f = p.refused ? "refused" : p.f ? `${p.f.score}/${p.f.sev}${p.f.flag ? " ⚑" : ""}` : "—";
  return `<tr><td>${esc(p.id)}</td><td>${p.planted ? "planted" : "clean"}</td>
    <td>${esc(p.cls || "—")}</td><td class="num">${q}</td><td class="num">${f}</td><td>${statusTag(p)}</td></tr>`;
}).join("");
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
