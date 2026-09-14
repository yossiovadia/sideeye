# Side-Eye calibration — Fable 5 judge: analysis

Generated: 2026-08-31 (analysis appended by hand; inputs below are machine-generated)

Inputs:
- `fable-5_verdicts.jsonl` — 59 judged pairs, rubric v3 (commit 60d1f92), judge
  `claude-fable-5` via the dogfood Anthropic gateway, temperature omitted
  (Fable rejects it, harness self-adapts).
- `qwen3.8_uncensored_4090_report.md` — 27B baseline, 58 judged pairs. **v2-era
  rubric** (generated 2026-08-30 19:41 PDT; v3 committed 2026-08-31 08:11).
- 27B post-v3 reference numbers from the baseline session: recall 17/23 judged
  (74%), incorrect_api_claim 8/10 post-v3 (3/10 pre-v3), false-flags 2/30.

## Headline scoreboard

| Metric | 27B (v2 report, committed) | 27B (post-v3 ref) | Fable 5 (v3, this run) |
|---|---|---|---|
| Recall, planted (judged) | 17/28 = 61% | 17/23 = 74% | **26/27 = 96%** |
| Recall, planted (of all 29) | 17/29 = 59% | — | 26/29 = 90% (4 refused) |
| False-flags, clean (judged) | 2/30 = 7% | 2/30 = 7% | 15/32 = 47% (**see audit**) |
| Refusals | 0 | — | 4 pairs (see below) |

## Per-class recall (planted)

| class | 27B (v2 report) | Fable 5 |
|---|---|---|
| incorrect_api_claim | 5/11 | **10/10** (1 refused: cal-03-p) |
| unverified_claim | 3/5 | **6/6** |
| subtle_logic_bug | 9/12 | **10/11** (1 refused: cal-06-p; 1 missed: cal-04-p) |
| all planted | 17/28 | 26/27 |

## Refusals (4 pairs — counted as unjudged)

Fable returned `stop_reason: "refusal"` (HTTP 200, zero content) on these,
deterministically across 16+ attempts per pair in two runs:

| id | truth | topic | 27B verdict |
|---|---|---|---|
| cal-03-clean | clean | reqwest client for an IdP JWKS endpoint (TLS, keys) | 5/none |
| cal-03-planted | incorrect_api_claim | same task, planted timeout() claim | 4/minor, not flagged |
| cal-06-planted | subtle_logic_bug | execute user-supplied SQL safely | 4/minor, not flagged |
| cal-13-clean | clean | stream a 100MB file download with Range support | 4/minor, not flagged |

All four are security/credential-adjacent content (identity-provider key
material, SQL-injection framing, bulk file transfer). Fable's safety layer
refuses to *grade* this class of content. This is a **coverage hole** for Fable
as an always-on judge: 2 of the 4 carry planted defects Fable never saw.
Do not "fix" this by rewording the rubric — that would invalidate the frozen
cross-judge comparison.

Harness note: `evaluate.py` now treats `stop_reason: "refusal"` as
`JudgeRefused` and fails fast instead of burning 8 retries (~1.3k wasted input
tokens per pair before the fix).

## Delta table: where Fable flagged differently than the 27B

### A. Planted — Fable caught, 27B (v2) missed (8 pairs)

| id | class | one-liner |
|---|---|---|
| cal-01-p | incorrect_api_claim | TrimPrefix "both ends" misstatement; Fable: major API error (27B noticed it but scored 4/minor) |
| cal-02-p | incorrect_api_claim | `errors='replace'` yields U+FFFD not '?'; Fable: major (27B: 4/minor) |
| cal-05-p | incorrect_api_claim | failureThreshold is consecutive-failure, not "rolling window"; Fable: major (27B: 5/none) |
| cal-09-p | subtle_logic_bug | jitter `(1+random)` never decorrelates below base delay; Fable: major (27B: 4/minor) |
| cal-10-p | unverified_claim | "guaranteed sub-microsecond" `time.monotonic()` claim; Fable: major (27B: 4/minor) |
| cal-11-p | incorrect_api_claim | `skip_serializing_if` does not control deserialization; Fable: major (27B: 4/minor) |
| cal-23-p | unverified_claim | "no additional round-trip" FIN guarantee + code missing `os` import; Fable: 2/major (27B: 4/minor) |
| cal-24-p | incorrect_api_claim | `tolerationSeconds` is invalid with NoSchedule; Fable: 2/major (27B: 4/minor) |

Caveat: the 27B column is v2-era. The post-v3 re-judge caught 8/10 API-claim
(3/10 pre-v3), so ~3 of the five API-claim rows above (of cal-01/02/05/11/24-p)
flip to "both caught" once the 27B post-v3 verdicts file is available. The
clean judge-vs-judge delta needs that file (it lives on the 27B box, not in
this repo).

### B. Planted — both missed (1 pair)

- cal-04-p (subtle_logic_bug): email-regex domain class `[a-zA-Z0-9.-]+`
  accepts `user@.com`; both judges scored 5/none — Fable called it "minor
  known edge-case laxity inherent to this approach". Arguably a design choice,
  not a bug — candidate for re-labeling, not a judge failure.

### C. Planted — 27B never judged, Fable caught (1 pair)

- cal-28-p (unverified_claim): log-bucketed "GK sketch" with evolving
  min/max bucket boundaries; Fable: 2/critical, "claimed error bound is
  fabricated". 27B never graded this pair.

### D. Clean — Fable flagged, 27B did not (13 pairs) — ALL AUDITED AS REAL

Each was read against the answer text; every claimed defect is genuine:

| id | defect Fable found |
|---|---|
| cal-06-c | "driver sends params out-of-band" — psycopg2 escapes client-side; same class as the planted API-claim defects |
| cal-07-c | `Mutex(...)` constructor + `move_to_front` on wrong type — does not compile |
| cal-08-c | ErrQuote/ErrBareQuote descriptions swapped vs Go's docs |
| cal-11-c | "Option fields are omitted by default" — serde serializes `null` without the attribute |
| cal-14-c | attributes undefined-return caching to the JSON *replacer*, which only affects arg keys |
| cal-15-c | inotify on a symlink-swapped ConfigMap mount never fires; busybox lacks inotifywait; no app actually runs |
| cal-20-c | `sem.clone()` — `Semaphore` is not `Clone`; does not compile |
| cal-23-c | asserts `Shutdown()` sets `r.Close = true` — invented mechanism |
| cal-26-c | example callback is `() => string` vs required `() => Promise<T>` — does not type-check |
| cal-28-c | not a GK sketch: d=0 on insert, wrong merge condition, query ignores Δ |
| cal-29-c | dialect-mixed pseudocode (MySQL LIMIT-in-IN-subquery is rejected); no per-batch COMMIT |
| ctrl-03 | `N - 1` underflows for `[T; 0]` — panics on an empty array |
| ctrl-05 | spurious trailing empty field when the line ends with a quoted field |

### E. Clean — both judges flagged (2 pairs) — also real

The 27B's two "false-flags" in the committed report were **correct catches**:

- cal-16-c: `Option::replace(Some(val))` type error + `!Sync` (UnsafeCell, no
  `unsafe impl Sync`) — an SPSC queue that cannot be shared.
- cal-27-c: the in-progress Event guard is never created (dead code) +
  ("done", None) contradicts the "re-execute" claim.

### Net

No pair exists where the 27B caught a planted defect and Fable missed one
(Fable's judged-and-caught set ⊇ 27B's, modulo the v2/v3 caveat). Fable's
"47% false-flag rate" is, after audit, a **100% true-positive rate** on the 15
clean pairs it flagged — the pool's clean labels are wrong on all 15.

## Clean-pool audit conclusion

15 of 34 "clean" answers (44%) contain at least one genuine latent defect. The
pool generator ships flawed answers, and neither the 27B judge nor the pool's
own validation caught any of the 15. The 17 clean pairs neither judge flagged
remain unaudited — at the generator's observed defect rate, treat "clean" as a
label, not a guarantee, until a human pass re-labels and re-freezes the pool.

**The pool must not be regenerated** (frozen yardstick rule); it needs a
human-audited re-labeling of the 15 pairs (plus review of the 17), then
re-freeze with corrected ground truth.

## Cost (real, from usage records in fable-5_verdicts.jsonl)

| item | input | output | cost @ $10/$50 per MTok |
|---|---|---|---|
| 59 judged pairs | 86,193 | 71,906 | **$4.46** |
| 64 refused attempts (4 pairs × 8 × 2 runs) | ~132,000 | 0 | ~$1.32 (not in verdicts file) |
| smoke + verification calls | ~3,000 | ~400 | ~$0.03 |
| **total** | | | **≈ $5.81** |

Fable verdicts are output-heavy (~1.2k output tokens/pair vs ~250 estimated),
which is what pushes per-pair cost to ~$0.075 instead of ~$0.015.

## Recommended next steps

1. Human-audit + re-label the 15 contaminated clean pairs (and review the 17
   unflagged ones), then re-freeze the pool. Until then, report Fable's
   clean-pair performance as "15/15 real defects found", not "47% false-flags".
2. Pull the 27B **post-v3** verdicts jsonl from the box to build the exact
   judge-vs-judge delta (removes the v2/v3 confound on the 5 API-claim rows).
3. Decide the refusal class: document as a known Fable coverage hole
   (security-adjacent grading content), or route that class to a different
   judge. Either way, meter it — 4/63 = 6.3% of this pool's content.
4. Commit the `evaluate.py` changes (usage logging, temperature
   self-adaptation, refusal fail-fast) so the next judge run inherits them.
