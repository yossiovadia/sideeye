# Side-Eye: Draft Cheap, Review Expensive

> **⚠️ Superseded as the plan.** The scope of record is
> [`sideeye-mvp-scope.md`](sideeye-mvp-scope.md) — Side-Eye is an **on-demand,
> human-triggered session review tool** (cheap model writes, you run one command,
> the strong model reviews). This document describes the *org-scale future
> program* (gateway sampling → shadow-pairwise → evidence-driven routing) and is
> kept only as reference, to revisit **if** the MVP proves out **and** org-scale
> routable traffic actually exists. **Do not treat anything below as the current
> plan.** The condensed version of this program lives in that scope note's
> appendix.

**Pitch: use our most capable model as a reviewer, not a generator — and build the measurement loop into the gateway.**

*Side-Eye is the working name for the Phase 1 primitive: it watches traffic
from the side and never interrupts it.*

---

## What I found

While working with two model tiers, I fell into a workflow by accident: I have a
capable-but-cheap model (Opus, 1M context) write code or plans, then ask our most
capable model (Fable 5) to *review* the result. The expensive model finds real,
substantive issues almost every time — issues the cheap model readily confirms and
fixes.

This isn't luck. It's an economic asymmetry in how LLM APIs are priced.

## Why it works

Every Claude tier charges **5× more for output tokens than input tokens**.
Generation is output-heavy; review is input-heavy. At current list prices:

| Task on the expensive model | Tokens (in / out) | Cost |
|---|---|---|
| Generate a feature end-to-end | ~100K / ~30K | **≈ $2.50+** |
| Review the finished diff | ~30K / ~1.5K | **≈ $0.38** |

A review pass captures most of the expensive model's quality advantage at
**~15% of its generation cost** — because verifying is easier than generating,
and a reviewer reads with full context but writes little.

## The proposal

Three phases, smallest first:

**Phase 1 — Side-Eye: judge sampling in the gateway (the ask).**
A Praxis filter that takes a configurable sample (e.g. 5–10%) of completed
request/response pairs and sends them — **together, as one grading request** —
to an expensive "judge" model, outside the request path. The judge grades the
response that was actually served; it never generates a competing answer. Its
structured verdict becomes per-route/per-model quality metrics.

What Phase 1 buys, stated honestly: it makes the population **legible**, not
safe. Sampling measures a model's *defect rate*; it does nothing about the
unsampled defects, which still ship. There are three cost terms —
generation, judging, and the cost of shipped defects (rework, incidents,
trust). Side-Eye shrinks generation, adds a small judging term, and leaves the
shipped-defect term to statistics. That's a legitimate design — it's how
manufacturing QA works — but the claim is "we can now *measure* quality per
route," never "quality is protected." Any pitch that says the latter has
oversold it.

**Phase 1.5 — shadow-pairwise: the routing-evidence bridge.**
Phase 1 scores the cheap model on traffic the cheap model *already* handles. The
routing decision needs a different number: the quality **delta** on the traffic
you'd *migrate*. Phase 1.5 gets it — see its own section below. It's the phase
that actually justifies Phase 2, and it's easy to skip by accident.

**Phase 2 — Evidence-driven routing.**
Once the delta evidence exists per model/route/task-class, we can confidently
route output-heavy, low-reasoning work (formatting, summarization, extraction)
to cheap models and keep frontier models for what actually needs them — with a
dashboard proving quality didn't move. Optionally, a synchronous "review gate"
mode for high-value routes (code generation): expensive model reviews, cheap
model revises, before delivery.

**Scoping honesty (the decomposition's weak seam).** Phase 1 measures whatever
traffic we point it at — today that's interactive dogfood coding sessions. But
the biggest Phase 2 prize (down-routing) is cleanest on *high-volume, uniform*
traffic — batch, CI, API integrations — and scores from interactive coding
sessions **do not transfer** to that traffic. So Phase 1 must eventually sample
the *actual* traffic Phase 2 will route. If that traffic doesn't exist in the
org yet, Side-Eye is honestly a measurement program with a routing story
attached — still valuable, but name which one is being pitched.

## How Phase 1 works — example flow

The important clarification: **Phase 1** is **not** shadow traffic. We don't send
the user's request to a second model to produce its own answer and compare two
answers (that would cost full generation price). We send the expensive judge
**the original request plus the cheap model's response**, and its only job is to
grade — the automated version of a code reviewer reading a PR without writing a
competing implementation.

(Shadow generation *does* reappear — deliberately and bounded — in Phase 1.5,
because grading cheap-on-cheap traffic can't tell you what happens when you move
*strong-model* traffic down. That's a separate, small, opt-in slice, not the
Phase 1 measurement loop.)

```
1. Client → Praxis → cheap model → response → client
   (unchanged; the user is served immediately, zero added latency)

2. For 1 in N responses (sampled), AFTER delivery, Praxis builds a
   NEW request to the judge model:

     [fixed rubric template — written once, lives in config]
     + the original user request        ("what was asked")
     + the cheap model's response       ("what was answered")

3. The judge returns a forced-JSON verdict, e.g.:
     { "score": 3,
       "issues": ["missed the error-handling requirement"],
       "severity": "major" }

4. Praxis records the verdict as a metric and moves on.
   The served response is never touched; no one acts on a single verdict.
```

Example rubric template (per route type, in config):

> *"You are grading a response, not answering the request. Given the user's
> request and the response below, score 1–5 on: answered what was asked,
> correctness, adherence to stated constraints. Return JSON only:
> {score, issues[], severity}."*

Individual verdicts are noisy and don't matter. The **aggregate** is the
deliverable — after a few weeks of sampling:

| Route / task type | Model | Avg score | Major-issue rate |
|---|---|---|---|
| summarization | Haiku | 4.6 | 1% |
| formatting / extraction | Haiku | 4.7 | 0.5% |
| code generation | Haiku | 3.1 | 18% |
| code generation | Sonnet | 4.4 | 3% |

That table answers "which traffic can we safely route to cheap models?" with
data instead of assumptions — and after any routing change, the same metric
shows immediately whether quality regressed. Judge noise averages out across
hundreds of samples per cell.

One statistical guard: cells are stratified by **task class** (the classifier
filter already produces it), never by route alone. A route whose traffic mix
shifts harder will show a score drop that looks like model regression but
isn't — comparisons must hold the task class fixed, or mix shift manufactures
phantom regressions and masks real ones.

Two hard constraints on that task-class taxonomy, both easy to get wrong:

- **Entry-observable.** A dimension the *router* can't see at request time is
  useless for routing, no matter how cleanly the *judge* can score it in
  hindsight. "Single- vs multi-file" fails (unknown at entry); route, caller,
  batch-vs-interactive, requested model, and context-size bucket pass (free and
  exact at entry). Subject tags ("rust", "terraform") are dead on arrival — a
  bottomless long tail. Categorize by what predicts the *cheap-vs-strong gap*,
  not by topic.
- **Gap-separating and data-pruned.** A dimension only earns a cell if the
  cheap-vs-strong quality gap actually *differs* across its values — and that's
  discovered from verdicts, not designed a priori. Start with 5–8 coarse cells,
  then let the data edit the taxonomy: cells with the same gap merge; a cell
  with huge internal variance means the dimension is wrong. And do the
  sample-size math first — at dogfood volume with 5–10% sampling, even a
  6-cell × 2-model grid takes *months* to reach a confidence interval that
  means anything, and every cell added roughly doubles that. Prefer the
  smallest taxonomy that isn't insulting. (This is a large part of why Phase 1.5
  pairwise, which needs no taxonomy, is the faster path to a routing decision.)

## Coding and agentic traffic: grade the session, not the turn

For agentic coding workloads, file contents are fully visible at the gateway —
a model "writing a file" is a tool call whose input carries the complete file
text, and each turn's request carries the conversation history including
everything previously read and written. So the judge sees the actual code.

But one response is one *turn* ("edit this function, run the tests"), not one
unit of work. Grading isolated mid-task turns is noise. For these routes, the
judge unit is the **session**:

1. Praxis groups traffic by session (conversation/session IDs, or shared
   history prefix — each request carries the full history, so this is tractable).
2. On session end (idle timeout), the **final request's history** is already the
   complete record: original ask, files read, files written, test output.
   One caveat: the OpenAI Responses API with `store: true` +
   `previous_response_id` does *not* resend history — but Praxis already runs
   the response store and rehydrate filters for exactly that API, so session
   reconstruction goes through the store we already maintain rather than
   assuming history-in-request.
3. That record goes to the judge with a code rubric: *"Did the work accomplish
   the ask? Are the written files correct and complete? Were test failures
   actually resolved?"*

Session-level judging is still input-heavy (a 150K-token session ≈ $1.50 at
Fable prices), so coding routes sample at a lower rate (2–5%) than one-shot
requests.

## Phase 1.5 — shadow-pairwise: where the routing evidence actually comes from

Phase 1 has a transfer-validity hole that's easy to miss: it grades the cheap
model on traffic the cheap model *already serves*. But the Phase 2 question is
"can we move traffic that's on the **strong** model **down** to the cheap one?"
— and the honest answer needs the **delta on that specific traffic**, not an
average of two separate populations.

Phase 1.5 measures it directly: for a small, opt-in slice of strong-model
traffic, mirror the request to the cheap model **out of band, after the user is
served** (zero added latency), then have the judge score the **two answers to
the same task, head-to-head**.

Why this is the right instrument, not scope creep:

- **Pairwise ≫ population means, statistically.** "Which of these two answers to
  the *same* task is better, and by how much" converges far faster than
  comparing the average of cheap-traffic scores to the average of
  strong-traffic scores. You reach a trustworthy answer in a fraction of the
  samples.
- **It needs no taxonomy to be meaningful.** A/B on identical inputs is
  interpretable per-request; you can bucket *after* the fact instead of guessing
  buckets first (see the taxonomy caveat below).
- **It produces the one artifact that convinces a route owner:** "we ran *your*
  actual traffic through both models — here is the quality delta." That's a
  migration decision people will sign off on; a population average isn't.

Cost is bounded the same way Phase 1 is — a low sample rate on opt-in routes —
but note it *does* include one extra cheap-model generation per sampled item
(the shadow answer), so it's priced above pure grading. It is the deliberate,
scoped return of "shadow traffic" that Phase 1 rightly avoids for its
measurement loop. **If you build only Phase 1 and jump to Phase 2, you are
routing on the wrong number.**

## Where the money actually is

To be direct about it: **Phase 1 saves nothing by itself — it costs ~$1–2K/month.**
It's the meter, not the cut. You don't save money by installing a power meter,
but you can't safely cut the power bill without one. The savings come from what
the meter makes possible:

**1. Phase 2 down-routing (the main line).** Today traffic defaults to
expensive models because nobody can prove a cheap model is good enough for any
given slice. Judge data identifies the slices where quality holds. Illustrative
math at current list prices (est., assumptions stated):

```
Assume 1M requests/month on Opus (avg 2K in / 500 out):
  per request: 2K × $5/M  + 0.5K × $25/M  = $0.0225   → $22.5K/month

Judge data shows 40% of traffic (summarization, formatting,
extraction) holds quality on Haiku:
  per request: 2K × $1/M  + 0.5K × $5/M   = $0.0045

Savings: 400K req × $0.018  ≈  $7.2K/month  (≈ $86K/year)
Against ~$1.5K/month judge cost — roughly 5:1, scaling linearly
with traffic volume and with how much traffic proves down-routable.
```

The 40% is the number nobody knows today — that's precisely what Phase 1
measures. If it turns out to be 15%, we learned that cheaply; if it's 60%,
the savings double.

One accounting honesty note. When the cheap model is a **self-hosted** model
(our dogfood Qwen), its dashboard cost of **$0 is a *marginal* figure — "no
extra API spend," not "free."** A self-hosted GPU is a fixed cost, and its real
per-token cost is a *utilization* function: at low volume it can exceed the
per-token price of an API model. The $0 is honest for "we added no API bill,"
but the Phase 2 business case must be stated with a **loaded GPU cost** (amortized
GPU-hours ÷ tokens served), not zero — and every projected number labeled an
estimate with its assumptions. A finance reviewer will unwind a $0 that isn't.

**2. The review gate — answering "but you're ADDING an expensive model."**
The fair objection: today we run Opus only; the review gate adds Fable calls,
so it increases spend versus today. True — **if quality is held at today's
level, don't turn the gate on** (it's per-route opt-in, off by default). The
gate saves money against a different baseline: the routes where Opus-level
quality *isn't* enough. For those, the alternatives are:

```
Get frontier quality by generating on Fable:      ≈ $2.50+ / task
Get it by Opus draft + Fable review + revise:     Opus cost + ≈ $0.40
```

Same quality bar, ~3–6× cheaper than the honest alternative. So the gate is
never "Fable on top of everything" — it's pennies of Fable placed exactly
where a penny of review replaces dollars of generation. And quality failures
carry their own cost line: every issue the review catches at draft time is a
rework loop that didn't happen — more Opus tokens re-prompting, and engineer
time, both of which dwarf $0.40 per task. One frame for the whole proposal:
**hold quality constant and the bill goes down; hold the bill constant and
quality goes up. Pick which one to bank, per route.**

**3. Regression insurance (defensive, real).** Provider model updates, prompt
drift, and guardrail failures currently surface as user complaints. A
continuous quality metric catches them in the dashboard instead. Hard to put
a dollar figure on until it fires the first time; teams that have it never
give it up.

## How "move traffic down" actually works

Three clarifications that head off the natural misreading ("you'll grab my
Opus session and shove it to Haiku mid-conversation"):

- **Judge data is used offline, as policy — never live.** Phase 1 produces
  aggregates ("Haiku averages 4.7 on summarization traffic"). A human turns
  those into a routing table ("summarization-class requests → Haiku tier").
  At request time only two cheap things happen: classify turn 1, look up the
  table. The judge is never consulted in the request path.
- **"Down" only happens at conversation birth.** A new conversation is
  classified once and pinned. Live sessions are never moved down — see the
  affinity policy below.
- **Only opted-in traffic is routed.** Down-routing applies to routes using
  a managed model alias (`model: auto`, or tenant-managed tiers). A caller
  that explicitly requests `opus-4.8` gets `opus-4.8` — silently serving a
  cheaper model against an explicit request is a trust violation, and the
  config enforces "explicit model = honored model."

## Phase 2 in real life: route conversations, not messages

The known failure mode of intelligent routing is multi-turn bounce
(vllm-project/semantic-router #1439, which we reported): a per-message router
classifies "looks good, commit it" as trivial and hands turn 2 of a complex
coding conversation to a tiny model, which answers with a platitude. Any
router that decides per-turn has this bug.

Phase 2 avoids it by making the routing unit the **conversation**:

- Classify at **turn 1**, pin the session to the selected model.
- Re-classify each turn for **upward escalation only** (a conversation that
  starts trivial and turns hard moves up; nothing moves down mid-session).
- New conversation → fresh decision. Session key from conversation/session ID
  headers, or a hash of the history prefix (each request carries full
  history). Praxis already holds cross-request state, so this is a natural
  gateway feature — the thing that made session affinity awkward in
  ext-proc-style routers.

The pricing enforces this policy anyway: **prompt caches are model-scoped.**
Mid-conversation, the pinned model reads history at ~0.1× input price; a
switched-to model reads it cold at full price. For a short follow-up with 50K
tokens of history, staying on cached Opus costs ≈ $0.026 while switching to
"5× cheaper" uncached Haiku costs ≈ $0.050 — de-escalating mid-conversation
*loses* money while risking the quality break. So down-routing decisions are
made once, at conversation start, where the cache argument doesn't apply.

The judge ties in twice: session-level grading catches any residual bounce
damage as a score drop on the dashboard (instead of a user complaint), and
pinned-vs-unpinned score distributions are the direct evidence that the
affinity policy is load-bearing.

## The review gate, concretely (opt-in routes only)

For routes that opt in — API-integrated workloads with a clean
request→deliverable shape (PR-description bots, report generators, batch
code-gen), not interactive chat — the gate runs the draft-cheap /
review-expensive loop inside the gateway:

```
1.  Cheap model (e.g. Opus) produces its final answer — Praxis holds it
2.  Praxis → expensive model (e.g. Fable): "review this"
        (conversation history + the held answer + a fixed rubric;
         no stored state needed — the in-flight request carries it all)
3.  Reviewer returns comments (short, input-heavy, ≈ $0.40)
4a. No significant issues → release the held answer unchanged
4b. Issues found → Praxis → cheap model: "address these review comments"
        → cheap model revises → release the REVISED answer
```

The expensive model never speaks to the user. Its comments feed back into
the cheap model, and the final text is genuinely the cheap model's — just
post-review. Praxis stamps the response (`x-praxis-ai-reviewed: true`) and
meters both models' token spend.

Failure modes are bounded by config, not hope: the review call has a hard
timeout, and on reviewer timeout or error the held answer is released
unreviewed with `x-praxis-ai-reviewed: false` and a metric — the gate must
never turn a judge outage into a serving outage. The revise loop runs **one
round**: review → revise → release. Revised answers feed back into normal
async judge sampling (see the revision-traffic lesson below), which is what
catches a bad revision — not a second synchronous round-trip.

For interactive clients (Claude Code, chat), the gate stays **off**: a proxy
can't push a review after the response is delivered, and blocking a human
mid-session on a review pass is the wrong trade. Those routes get the async
judge (metrics, zero latency) — the review loop belongs client-side there,
where the user already runs it by hand today.

It's the same review loop everywhere; what differs is who pulls the trigger:

| Variant | Trigger | Audience | Infrastructure |
|---|---|---|---|
| MCP tool / slash command ("review this") | A human, on demand | Interactive users (Claude Code) | ~A day of work, no gateway changes — the automated form of the manual workflow that motivated this pitch |
| Side-Eye (async judge) | A sample rate | Every route, silently | The Phase 1 filter |
| Review gate | The request itself | API/deliverable services | Phase 2, opt-in per route |

The MCP variant ships first and doubles as the live demo; it does not replace
the other two — a human-triggered review is a biased sample (people ask when
they already suspect a problem) and services never ask at all.

## Deployment tiers: what the judge can see and do

The manual workflow that motivated this pitch quietly used capabilities a
deployed judge doesn't automatically have. Two field cases
(`benchmark-results.md`, field evidence 1 and 2) produced findings that sort
cleanly by the capability each one required:

| Finding (real, from field evidence) | Needed | Tier |
|---|---|---|
| TLS verification disabled in the diff | read the request/response pair | 0 |
| Doc claim contradicted by a file elsewhere in the PR | read the whole session/PR context | 1 |
| Dead match arm (`"::1"` vs bracketed `"[::1]"`) | read a *dependency's* source | 2 |
| Test suite green piped, red on a real terminal | **run an experiment** (PTY) | 2 |

So "the judge" is three deployables, not one:

- **Tier 0 — pair grading.** Phase 1 exactly as pitched above: stateless
  grading of sampled request/response pairs, in-gateway, async. It is the
  measurement layer and loses nothing in deployment; nothing about the manual
  workflow was load-bearing here.
- **Tier 1 — session grading.** Also gateway-native (the session section
  above). The evidence a reviewer needs — diffs, tool output, test runs —
  already flows through the gateway inside agent conversation histories.
  Read-only but evidence-rich; the rubric's job is *cross-checking claims
  against the execution evidence in the transcript* ("the comment says tests
  can't run on a TTY — does any tool output support that?"), which is where
  artifact-only judges are weakest.
- **Tier 2 — agentic verification.** Reading dependency sources, checking
  out PR heads, running experiments. This is **not a filter and never can
  be** — it's a workload with a sandbox, tools, and scoped repo credentials.
  Deployed shape: the gateway samples and flags ("this session is PR-bound"),
  emits an event, and an out-of-band **judge-worker service** — an agent
  runner with a sandboxed workspace — picks it up, verifies, and writes the
  verdict back to the same metrics ledger (and optionally a PR comment). The
  gateway's role is sampling, evidence capture, and verdict ledger; the
  executor is a sibling service it feeds. In the manual workflow, a human
  was personally playing event bus and sandbox; deployment names those two
  roles and gives them to software.

Cost scales with the tier: tier 0 ≈ $0.02/verdict, tier 1 ≈ $1–2/session,
tier 2 ≈ a full agent session ($5–15) — so tier 2 is gated to high-value,
PR-bound routes at low sample rates, which is where its findings (both field
cases were merge blockers) repay it outright. Phase 1's ask is tier 0 + the
tier-1 rubric; tier 2 is the honest name for what Phase 2's review gate
grows into on code routes.

One more lesson from the field evidence: **revision traffic gets judged like
first drafts.** Both cases converged only after a second review cycle — fix
commits carried residue of the original defect in files the fix missed *and*
introduced new defects of their own. Sampling must not exempt "fix" turns as
already-reviewed.

## Do we need VSR (semantic-router)?

**Not for Phase 1.** VSR and judge sampling answer different questions:

- VSR decides *where to send a request* (pre-request classification).
- Judge sampling measures *how good the answer was* (post-response evaluation).

Phase 1 is self-contained in Praxis: a response-path filter, one async HTTP call,
Prometheus metrics. If we later adopt VSR (or build routing into Praxis's existing
inference-routing filter), judge scores are exactly the calibration data that
makes routing trustworthy instead of guesswork. So VSR is a potential *consumer*
of this work, not a dependency.

## Why the gateway is the right layer

Praxis already sits on every request/response pair and already meters tokens.
It's the one place that sees all traffic across all models and teams — which
makes it the natural vantage point for sampling, judging, and reporting quality
per route. No client changes, works for any OpenAI/Anthropic-compatible caller.

Implementation note: sampled pairs are teed into Praxis's existing response-store
machinery (`ResponseStoreRegistry`) and judged asynchronously from there — the
streaming hot path stays untouched, consistent with our no-full-response-buffering
rule.

## Cost envelope

Bounded by the sample rate, and input-priced:

- One-shot requests: ~$0.02 per judged request → roughly **$1–2K/month** at
  1M requests/month with 10% sampling.
- Agentic sessions: ~$1–2 per judged session at 2–5% sampling.

Both are tuning knobs, per route, in config.

## Known limitations (designed around, not ignored)

- **The judge isn't an oracle — anchor it to ground truth.** The judge is a
  *proxy* for quality. For coding traffic, harder signals already exist and cost
  nothing to collect: did CI pass, was the PR merged, was it reverted, did the
  human immediately rewrite the answer. Judge scores must be *correlated against
  those outcomes*, not trusted in a vacuum — an uncorrelated scoreboard is a
  confidence trick. Verdicts use a fixed rubric with severity, only aggregates
  drive decisions, and anything auto-acted-on is gated on objective checks
  (tests, schema validation), not the judge's word alone.
- **Tier-1 is blind exactly where cheap models fail.** A read-only judge scores
  "looks-right" code highly; the defects that actually distinguish a cheap model
  are often execution-dependent (plausible code that doesn't run right) — which
  tier-1 cannot see. Routing purely on tier-1 scores therefore *selects for
  judge-invisible failure*. Counter: a small, periodic **tier-2 audit** (check
  out the code, run the tests) to calibrate the tier-1 blind spot per task class,
  plus an evidence-demanding rubric that scores down unsupported "I tested it"
  claims.
- **The judge must itself be calibrated — once scores drive routing, they
  become a target.** Two guards: (1) a small human-labeled calibration set
  at bootstrap, with judge–human agreement tracked as its own dashboard
  metric — if agreement drifts, the judge (or rubric) regressed before any
  routing table does; (2) rubrics are versioned config, so a score shift can
  always be attributed to "rubric changed" vs "traffic changed" vs "model
  changed." Prompt tuning that games a fixed rubric shows up as
  rising judge scores with flat objective checks — that divergence is
  itself an alert. The calibration set is **frozen and re-judged on every
  rubric/judge change**, so a score shift is attributable to the pipeline vs.
  the traffic — otherwise the first rubric tweak reads as a model regression.
- **The social kill-switch — design the bad week before it happens.** One
  visible incident on down-routed traffic, while the dashboard reads 4.2/5,
  ends the program *politically* regardless of what the statistics say. Phase 2
  routing therefore needs a **per-route instant revert** and a **fast
  rolling-window regression alarm** (not a monthly chart) — so a bad slice is
  caught and rolled back in hours, and the response to "your cheap model shipped
  a bug" is "already reverted that route, here's the window," not a debate about
  averages.
- **Privacy/data handling.** Judging sends sampled payloads to the judge model —
  same provider and same data as the original traffic, but it is a secondary
  use, so judging is per-route **opt-in** in config. Sampled pairs teed into
  the response store are subject to a retention window (config, default
  weeks not months) — the store is a judging queue plus enough history to
  investigate score movements, not an archive.
- **The synchronous review-gate variant adds latency**; it's for code, plans,
  and reports — not chat. Phase 1 (async) has no latency impact at all.

## Further out: prompting-efficiency insights (dogfood synergy)

The dogfood project already meters **cost per user**; Side-Eye adds **quality
per route** — together they enable a metric almost nobody has: quality per
dollar. One forward-looking consumer of that data: mine high-scoring sessions
for teachable patterns (contrastive analysis of efficient vs. inefficient
sessions *within the same task class* — normalization matters, since harder
tasks naturally need more correction), and turn the findings into an org
prompting playbook plus opt-in, private, self-service coaching ("your two
habits that cost you retries"). Enablement only: aggregate pattern mining,
no user rankings — the goal is that everyone drives the cheap models the way
the best sessions already do.

## The ask

A small, time-boxed prototype: one Praxis filter (sample → store → judge →
metrics), one Grafana panel, run against our own traffic for a few weeks.
Output: real per-model quality data and a go/no-go basis for Phase 2 routing —
specifically, the measured answer to "what share of our traffic can run on
models 5× cheaper without quality loss," which is the number the savings
case stands on.
The manual draft-cheap/review-expensive workflow costs nothing and is already
paying off — this makes it infrastructure.
