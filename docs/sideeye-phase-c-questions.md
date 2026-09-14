# Side-Eye — two design questions for review

Self-contained brief (the reviewer has none of the build context). Please weigh
in on both problems below.

## Background

**Side-Eye** is a "draft cheap, review expensive" pattern for an AI gateway:
a cheap/free model does the work; a sample of its output is sent to an expensive
"judge" model, asynchronously, outside the request path, to measure quality per
model/route. Three modes exist in the design: (1) **async judge sampling**
(automatic, post-hoc, aggregate metrics), (2) a synchronous **review gate**
(opt-in routes: expensive model reviews, cheap model revises, before delivery),
and (3) a human-triggered **"review this" MCP/slash-command** (on demand).

Tiers by what the judge can see/do: **tier 0** = grade the request/response pair
(artifact only); **tier 1** = grade the whole session transcript; **tier 2** =
agentic judge that can run code/tests (a separate worker, not a filter).

**POC context.** Generator = GLM-5.2 (free, internal, via the Codex CLI). Judge =
Claude (Sonnet 5 default; Opus 4.8 / Fable 5 on escalation), routed through our
metered gateway so judge spend is visible. GLM traffic flows
`Codex → local praxis gateway → GLM`, so GLM tokens show at $0 on our dashboard.
Phase C's goal: automatically capture completed Codex→GLM **sessions** and send
each transcript to the judge (tier-1). The gateway is **praxis** (Rust/Pingora).

An empirical result that motivates question 2: on a curated hard-task test, the
tier-0 judge correctly caught a plausible-but-wrong API claim and an unsupported
"tests pass" claim, but **missed** an execution-dependent defect — a Rust test
that passes when stdout is piped (CI/agent harness) yet fails on a real TTY.
That class is structurally invisible to an artifact-only judge; catching it
required *running* the code.

---

## Problem 1 — the capture mechanism doesn't fit the client

The plan assumed: *"praxis's response store is the capture mechanism; don't
build one."* Reading the praxis source shows that's incompatible with the client:

- praxis's response store persists **only** OpenAI **Responses API** traffic
  (`POST /v1/responses`); persistence is gated on an `is_responses_create`
  classifier.
- Codex uses `wire_api="chat"` → `POST /v1/chat/completions`.
- **Nothing** in praxis persists `/v1/chat/completions` request/response bodies
  (a grep of the filters for any file/DB write found none). `token_count` and
  `external_metering` read chat bodies but extract only tokens/model — they never
  store prompt/answer text.
- GLM/LiteLLM does not serve the Responses API, and praxis does not translate
  Responses→chat to a chat-only upstream.

So "the sampler reads completed sessions from the response store" is impossible
with the Codex-chat client. Options:

- **A — capture from Codex's own session rollout logs**
  (`~/.codex/sessions/.../rollout-*.jsonl`, a full transcript per session).
  No praxis changes; consumes an existing artifact; yields the full tier-1
  session unit. Deviation: capture is **client-specific**, not gateway-native.
- **B — build a new praxis filter** that persists chat/completions bodies
  (`BodyAccess::ReadOnly` + `StreamBuffer`, templated on the Responses store).
  Gateway-native and production-shaped — but net-new Rust in the proxy, a
  rebuild, and it *is* "building a capture mechanism" (which the POC scope
  excluded).
- **C — route via the Responses API** — dead end (GLM has no Responses API).

**Proposed for the POC: A** (in-scope, full transcript, no proxy changes), with
**B** named as the eventual production path.

**Questions for the reviewer:**
1. Is **A** the right POC call, or does capturing from *client* logs undermine
   the core thesis (that the **gateway** is the right layer to capture and
   judge)? Is proving Side-Eye on a client-specific capture a meaningful proof?
2. For the product, is **B** (a gateway chat-capture filter) the correct
   primitive, or is there a cleaner one — e.g. generalizing the existing
   Responses store to chat, or a sampling tap on the body buffer `token_count`
   already materializes transiently?
3. Any risk in **A** we're missing — client logs diverging from what the gateway
   actually served, streaming/tool-call fidelity, or multi-client coverage?

---

## Problem 2 — should on-demand human escalation be a first-class mode?

Proposed new capability: let the human explicitly escalate a specific cheap-model
answer to the expensive model — *"I'm not sure about this; get a second
opinion."* This targets exactly the limitation measured above: a human who is
unsure can escalate the execution-dependent / subtle cases an automatic
artifact-judge can't flag. It overlaps the existing human-triggered "review this"
variant, but framed as **user-driven escalation** rather than scheduled sampling.

**Design questions:**
- **Semantics:** does "escalate" mean the expensive model **reviews** the cheap
  answer (critique → cheap model revises), or **re-answers** the turn itself?
  Or is it the user's choice per invocation?
- **Trigger surface** for interactive coding clients (Codex, Claude Code):
  (a) client-side MCP tool / slash command; (b) a gateway-side sentinel (a
  header or an `/escalate` token praxis detects and routes upward); (c) an
  out-of-band CLI that grabs the last session and sends it to the judge. Which
  is least friction and most faithful?
- **Judge tier/model** for escalation: Opus 4.8 / Fable 5 with a review rubric,
  vs the Sonnet 5 default. Cost per escalation, and who pays.
- **Bias:** user-driven escalation is a biased sample (people escalate when they
  already suspect trouble). Is that a defect, or the point — the human providing
  the tier-2 sampling signal automation cannot?
- **POC MVP:** escalation ≈ "run the judge on the *current* session now, on
  demand, with a stronger model + review rubric" — the same machinery as the
  async sampler, manually triggered. Is that the right MVP, or should it be a
  proper client integration from the start?

**Question for the reviewer:** Is on-demand human escalation worth first-classing
as a fourth Side-Eye mode? What's the cleanest trigger for interactive clients,
and should the default be review-vs-reanswer? Given it catches precisely the
execution-dependent class the artifact judge misses, does it meaningfully
complement the automatic tiers — or is it just the "review this" variant renamed?

---

## Resolution (review, 2026-08-24)

The load-bearing factual claim (response store = Responses-API-only; chat bodies
unpersisted) was independently verified against source. Decisions:

### Problem 1 — capture

- **POC uses Option A (Codex rollout logs), reframed: A is a scaffold, not the
  architecture.** The POC's thesis is *judge economics + quality signal at
  acceptable cost*, not capture. Capture is plumbing — prove the judge with any
  free transcript source and say so out loud.
- **Define a capture-agnostic transcript schema — the decision that matters now.**
  A normalized session unit the judge consumes; the rollout-log reader is merely
  **adapter #1**, a gateway tap is **adapter #2**. Then A-vs-B stops being a fork:
  two adapters into the same pipe, and every POC result carries to the production
  path unchanged.
- **Production capture is NOT "persist all chat bodies."** It's a **sampling tap**:
  decide at request time whether this request is sampled (N%), and only then
  buffer + export the pair to an external sink (file / queue / HTTP collector).
  Why: storing 100% to judge 1% is waste and violates the repo's no-stream-buffer
  rule; and it matches the pitch's tier-2 shape ("judge-worker fed by gateway
  events, NOT a filter"). So reshape "B" from *chat store* to *sampling tap
  emitting events*.
- **The gateway CAN do tier-1.** chat/completions is stateless — every turn
  resends full history — so a session's final request ≈ the whole tier-1
  transcript. Keep the longest-prefix-latest pair per conversation; no session
  stitching needed. This weakens the "gateway can't see sessions" worry.
- **Risk to state in the pitch:** client logs are the *client's* view. The moment
  praxis mutates a request (prompt_enrich, headroom compression, model_rewrite —
  all real filters here), the rollout log shows a transcript that never crossed
  the wire → judging the wrong artifact. Fine for the GLM POC (no mutation on
  that route), but it is the strongest single argument for gateway-side
  production capture. Plus: Codex-only coverage, and reading `~/.codex/sessions`
  is dogfood-acceptable, product-unacceptable.

### Problem 2 — on-demand escalation

- **First-class it — as the fourth trigger, not a fourth system.** One
  judge-invocation path, three triggers: scheduled sample / review gate / human.
- **Review, not re-answer (default).** Re-answer breaks session continuity, costs
  more, and produces nothing aggregatable; a review verdict is commensurable with
  the async judge's verdicts and feeds the same metrics.
- **Trigger: (c) out-of-band CLI for the POC → (a) MCP tool for the product;
  kill (b) the gateway sentinel.** Magic tokens in prompts are fragile, get sent
  to the model, poison prompt caching, and a CLI user can't type headers anyway.
  "Grab last rollout, send to judge" is a ~20-line script and *is* the MVP.
- **Never pool escalated verdicts with random samples.** Two labeled streams:
  random sampling = the unbiased per-model quality estimate; escalations =
  high-yield defect discovery and a growing curated hard-set for calibrating the
  auto-judge. The selection bias isn't tolerated, it's the point — keep it
  separate so it doesn't skew the scoreboard.
- **Judge defaults higher on escalation** (Opus 4.8; Fable for the nasty ones):
  the human already paid attention, so the prior of a real defect is elevated and
  volume is human-bounded, so cost is too. Sonnet-by-default is for the firehose.
- **Escalation gives selection, not capability — so it carries a tier knob, not
  just a model knob.** The hard-03 TTY defect is unseeable by *any* artifact
  judge, regardless of model. Default tier-1 review with a strong model; tier-2
  agentic dispatch ("does this actually work") when that's the question. The human
  supplies the tier-2 *targeting* that makes tier-2 cost affordable.

### TL;DR

A with a capture-agnostic schema; B reshaped from "chat store" to "sampling tap
emitting events"; fourth mode yes — review-default, CLI-then-MCP, never pool
escalated verdicts with random samples, and give escalation a **tier** knob
because the gap it closes is execution, not intelligence.
