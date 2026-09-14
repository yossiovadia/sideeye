# AI Inference Cost Savings — Distilled Ideas

Distilled from the VSR/Headroom/Hindsight exploration (`vsr-cost-savings`),
keeping only the ideas that survived review: correct math, honest baselines,
and architecturally sound placement. Adds one new pattern (draft-cheap /
review-expensive) and maps everything onto where it belongs relative to
Praxis (the AI gateway).

**Pricing basis (verified August 2026, Anthropic list prices per MTok):**

| Model | Input | Output |
|---|---|---|
| Claude Fable 5 | $10.00 | $50.00 |
| Claude Opus 5 / 4.6–4.8 | $5.00 | $25.00 |
| Claude Sonnet 5 | $3.00 ($2.00 intro) | $15.00 ($10.00 intro) |
| Claude Haiku 4.5 | $1.00 | $5.00 |

Prompt caching: cache reads ~0.1× input price, writes 1.25× (5m TTL).
Batch API: 50% off everything. Any cost analysis that ignores these two is
comparing against a strawman.

---

## 1. The honest baseline: caching + batch before architecture

Before proposing any routing/compression/memory system, the baseline must
already include the two zero-architecture levers:

- **Prompt caching** — repeated prefix content (system prompts, memory
  context, conversation history) at ~0.1× input price. A workload that
  re-sends a stable 100K-token context per request drops ~90% of that cost
  with one `cache_control` field.
- **Batch API** — 50% off for anything non-interactive (overnight agentic
  runs, bulk processing, evals).

Corollary that kills naive per-step model routing: **caches are
model-scoped.** Switching models mid-conversation forfeits the ~90% cache
discount on the shared history. Any architecture that bounces a conversation
between models must show its savings *net of the caching it destroys*.

The ideas below are the ones that survive this baseline — they save costs
caching can't touch (output tokens, wrong-model selection, redundant calls).

## 2. Output-token dominance

The sharpest single insight from the original exploration, and it got
*stronger* at current pricing: output costs 5× input on every Claude tier.
Consequences:

- **Input compression has a hard ceiling.** For a typical 2K-in / 500-out
  request, an 80% input compression saves only ~35% per request. Compression
  is transformative only for input-dominated workloads (RAG, document
  analysis, long histories) — and there it competes directly with prompt
  caching, which is free.
- **The biggest lever is routing output-heavy work to cheap models.**
  Formatting, summarization, extraction, commit messages — high output
  volume, low reasoning demand. Moving these from Opus ($25/M out) to Haiku
  ($5/M out) or a local model beats any input-side optimization.
- **Constraining output length** (structured output schemas, explicit
  length instructions) is a direct cost lever people forget.

## 3. Routing, with quality insurance

Semantic routing (VSR-style: route simple work to cheap models, complex work
to frontier) is real and proven — but its economics live or die on **routing
accuracy**, and the dangerous failure mode is over-deflection (complex
request → cheap model → bad answer → retry on frontier → paid twice, plus
quality damage).

Two ideas that survived:

- **Session stickiness as quality insurance.** Per-message routing misroutes
  multi-turn follow-ups ("yes, go ahead" scores as trivial) — documented as
  vllm-project/semantic-router #1439. A lightweight session pin keeps
  follow-ups to a complex task on the capable model. Honest framing: the pin
  doesn't save money directly — it makes *aggressive down-routing safe*, and
  the down-routing saves the money. The policy is simpler than
  momentum-filter approaches (VSR PR #1459): pin at turn 1, escalate up
  only, never de-escalate mid-conversation — because model-scoped prompt
  caches make mid-conversation down-switching a cost *loss* (cached input at
  0.1× on the pinned model beats full price on a nominally cheaper one), not
  just a quality risk. Down-routing decisions belong at conversation start.
- **Compression ratio as a free routing signal.** If compression already runs
  in the pipeline, its ratio is a zero-cost proxy for information density
  (boilerplate compresses; novel reasoning doesn't). One signal among
  several, never alone — dense-but-trivial and repetitive-but-hard requests
  both fool it. Define the metric once and unambiguously (fraction removed
  vs. output/input burned the original doc).

Rollout pattern for anything routing-shaped: **shadow mode first** (log what
would change, act on nothing) → quality comparison → gradual ramp with a
kill switch → per-tier metrics so every claimed saving is independently
auditable.

## 4. Draft cheap, review expensive (new)

Empirical origin: a workflow using Opus 4.6 (1M context, effectively free
under current access) to write code/plans, then prompting Fable 5 to review
the result. The expensive model found real issues nearly every time, and the
cheap model could apply the fixes.

**Why the economics work — it's output-token dominance again, inverted.**
Generation is output-heavy at the expensive rate; review is input-heavy at
the cheap rate. Concrete example at list prices:

```
Fable 5 generates a feature (agentic, ~100K in / ~30K out):  ≈ $2.50+
Fable 5 reviews the finished diff (~30K in / ~1.5K out):     ≈ $0.38
```

The review pass costs ~15% of expensive-model generation while capturing a
large share of the quality delta — because *verification is easier than
generation*, and the reviewer reads with full context but writes little.

**Generalized pattern — the critique cascade:**

```
cheap model generates → expensive model reviews (short, structured output)
→ cheap model revises → (optional) expensive model approves
```

This is the inverse of classic cascades (FrugalGPT-style: cheap first,
*escalate generation* on low confidence). Here the expensive model never
generates the artifact — it only judges. Prior art that validates the shape:
Anthropic's **advisor tool** (`advisor_20260301`) productizes exactly this —
a cheap executor model consults a more capable advisor mid-task. Our version
differs in placement (post-hoc review vs. mid-generation consultation) but
the executor/advisor economics are the same.

**Caveats to design around:**

- Reviewer critiques aren't oracle truth, and the cheap model is
  sycophancy-prone ("wow, great comment") — it may accept bad advice as
  readily as good. Require confidence/severity per finding, and gate fixes
  on something objective (tests pass, schema validates) rather than on the
  reviewer's word.
- The loop only pays when cheap drafts are *near*-acceptable. If the cheap
  model's draft is structurally wrong, review-revise cycles cost more than
  generating expensive-first. The classifier question "is this task within
  the cheap model's competence?" doesn't go away — it moves.
- Synchronous review doubles latency. Fine for code/plans/documents; wrong
  for chat.

**Two deployment variants, at different layers:**

| Variant | Layer | Latency cost | What it buys |
|---|---|---|---|
| **Synchronous review gate** — expensive review blocks delivery, cheap model revises | Client / orchestration (or the API's advisor tool) | High (2–3 round trips) | Quality floor on deliverables at ~15–25% of expensive-generation cost |
| **Async judge sampling** — gateway sends N% of (request + response) pairs to an expensive judge for grading, out of the request path | **Gateway (Praxis)** | Zero | Ground-truth quality scores per route/model/task-type; cost bounded by sample rate |

The async variant is the architecturally interesting one, because it solves
the biggest hole in every routing proposal: **routing accuracy claims with
no ground truth.** "85% → 92% accuracy" numbers are made up until something
measures them. An expensive-model judge sampling 5–10% of down-routed
traffic produces exactly the labeled data that calibrates routing
thresholds, tag boosts, and signal weights — continuously, in production,
for a bounded cost. The judge is the missing eval loop.

Two mechanics worth pinning down (both detailed in
`judge-sampling-pitch.md`):

- **The judge grades, it never re-generates.** The sampled unit sent to the
  judge is the original request *plus* the served response, with a fixed
  rubric; the judge returns a structured verdict. No shadow generation, no
  answer-vs-answer comparison — that's what keeps the cost at input-token
  prices.
- **For agentic/coding traffic, the judge unit is the session, not the
  turn.** File contents are visible at the gateway (they ride inside tool
  calls, and each request carries full history), but a single response is
  one mid-task turn. Judge on session end, using the final request's
  history as the complete record, at a lower sample rate.

## 5. Where each idea belongs (the Praxis question)

The original exploration never asked which layer owns what. Sorted:

**Gateway layer (Praxis is the right home):**
- Routing signals and model selection (classify → route → branch is already
  the Praxis pattern: `x-praxis-ai-*` headers → cluster selection)
- Token usage metering (already exists: `token_usage` filter)
- Session-stickiness tags for routing (a lightweight state store keyed by
  session, consulted at route time)
- **Async judge sampling** — the gateway sees every request/response pair,
  making it the natural vantage point for mirroring samples to a judge and
  emitting quality metrics per route
- Enforcing caching hygiene (detecting cache-hostile request patterns is a
  plausible future filter)

**Orchestration / client layer (not the proxy's job):**
- The synchronous draft→review→revise loop (the workflow decides what
  "review" means; the advisor tool exists for the in-band version)
- Compiled/deterministic workflow execution (a proxy sees opaque JSON; it
  can't compile business logic it doesn't own)

**Platform layer (fed by gateway telemetry, not implemented in it):**
- Distillation of high-volume task patterns — the gateway *collects the
  traces*; training and eval ownership live with the platform and the
  customer's ground truth

## 6. What was dropped, and why

For the record, ideas from the original exploration that did **not** survive:

- **Reversible memory compression (CCR bridge)** — its baseline ignored
  prompt caching; with caching, raw injection of stable memory context is
  already ~90% off, erasing most of the claimed 83% saving for 12 weeks of
  work.
- **Per-step model routing for agentic loops** — model-scoped caches mean
  every model switch re-pays full price on shared history; the doc's math
  hid this. Viable only where steps have genuinely small, separable contexts.
- **Semantic response caching (serving cached answers to "similar"
  questions)** — safe hit rates on non-FAQ traffic are low single digits;
  the wrong-cached-answer failure mode is worse than the cost it saves.
- **Headline dollar projections** — all computed at 3×-stale Opus pricing
  ($15/$75 vs. today's $5/$25). Percentages partially survive; the payback
  claims ("pays for itself in a month at 1K req/day") do not.

## 7. Suggested next step

Prototype the cheapest, highest-information piece first: **async judge
sampling as a Praxis filter concept.** Mirror a configurable sample of
responses (per route/model) to a configured judge model with a fixed rubric,
emit a quality score as a metric. No request-path latency, bounded cost,
and it produces the evidence that either justifies or kills every other
routing investment. The draft→review workflow that motivated this document
keeps working manually in the meantime — it needs no infrastructure to be
useful.
