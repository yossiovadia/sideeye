# Side-Eye MVP — On-Demand Session Review

**One sentence:** a cheap local model (Qwen/GLM) writes the code; on demand,
Fable reads the finished session and reviews it — so you get near-frontier
trust at a fraction of frontier cost.

This note is the scope of record. It deliberately replaces the phased
program (measurement → shadow → routing) with the small tool that motivated
it. The program material is demoted to the appendix, to be revisited only
if the MVP proves out and org-scale traffic exists to route.

## Why the economics work

Anthropic pricing is asymmetric: output tokens cost ~5× input tokens.
A coding session is output-heavy for the generator but input-heavy for a
reviewer.

- Frontier model **doing** the work: pays frontier output rates on all
  generated code plus repeated context reads. Est. $10–30 per real session.
- Frontier model **reviewing** the work: one input-heavy read
  (transcript + diff, ~100k tokens) plus a few k tokens of critique.
  Est. $2–4 per session.

So even reviewing **100% of sessions**, cost lands around 15–25% of
frontier-generates-everything. Sampling, task taxonomies, and routing exist
only to make the numbers work at org scale — at personal/team scale, review
everything.

(All numbers are estimates at list pricing; the metered gateway makes the
actual judge spend visible per review.)

## Scope — what the MVP is

1. **Trigger: the human.** An out-of-band CLI command (working name:
   `sideeye review`) grabs the last/current coding session, builds the
   review packet, sends it to the judge through the metered gateway, and
   prints the verdict. No client integration, no gateway changes, no
   sampling daemon. "The model asked me to pick a design option and I'm
   unsure" is not a feature — it is the moment you run the command.
2. **Judge: Fable (or Opus) with a review rubric.** Escalation volume is
   human-bounded, so use the strong model by default.
3. **Semantics: review, not re-answer.** The judge critiques (score,
   answered-the-ask, correctness, claims-vs-evidence, issues w/ severity);
   the cheap model (or the human) revises. Re-answering breaks session
   continuity and destroys the cost asymmetry.
4. **Sighted packet (required — a blind review is worthless):**
   - Final-state code of touched files with change markers, via
     `git diff -U999999` (full-file context). New files are full content,
     100% attributed — no special handling.
   - Execution evidence: test/build tool outputs, head+tail capped
     (never mid-truncated; always retain the summary line and exit code).
   - Coverage manifest: every touched file — path, size, lines changed,
     edit count, view rendered, what was elided. The judge must know when
     its view is partial.
   - Oversized files degrade to standard hunks flagged `view: partial`;
     the rubric scores those "not assessable," never guessed.
5. **Rubric rule:** the judge cannot execute code. A claim of execution
   ("tests pass") counts only if matched to captured output in the evidence
   section; an unmatched claim scores against claims-vs-evidence regardless
   of how plausible the code looks.
6. **Every verdict is saved and version-stamped** (adapter version, judge
   model, rubric version). This is not bookkeeping — the verdict corpus that
   accumulates from daily use *is* the future evidence base, grown from real
   usage instead of an upfront measurement program.

## Out of scope (shelved, not rejected)

- Automatic sampling streams (random %, per-model dashboards)
- Task-type taxonomy and entry-time classification
- Traffic routing (Phase 2), shadow/pairwise evaluation (Phase 1.5)
- Synchronous review gates in the request path
- Blind-vs-sighted as a standing mode — run it **once** as a demo
  (re-judge one session both ways, publish the delta), then retire blind
  except for sessions with no code.

## Known limits (stated, not solved)

- A Fable review is a tier-1 read: it catches **unsupported** claims, not
  **unsound** ones. An execution-dependent defect with genuinely passing
  output in the transcript will be missed. Run the tests yourself; an
  agentic (tier-2) judge is future work.
- New files can be graded on their content but not on repo fit (duplication,
  conventions) — scored "not assessable" on that dimension.
- Sessions may contain secrets/proprietary code; the packet goes to an
  external API. Fine for self-dogfood; redaction/consent is a prerequisite
  for any team-wide rollout.

## Success criteria

The MVP has proven out when, after a few weeks of daily use:

1. Reviews have caught real issues the author would have shipped
   (kept as receipts in the verdict corpus).
2. Judge spend per session, from the metered gateway, confirms the
   ~15–25%-of-frontier estimate.
3. The workflow is low-friction enough that it actually gets used
   unprompted.

That corpus — real defects caught, real costs measured — is the org pitch.
Not an architecture document.

---

## Appendix — the shelved program (context only)

The earlier design explored a phased org-scale system: **Phase 1**
gateway-sampled async judging (random + escalation streams, blind/sighted
A/B, per-model × task-type scores), **Phase 1.5** shadow-pairwise
evaluation on migratable traffic, **Phase 2** evidence-driven routing with
regression auditing. Key open problems recorded during review, for whoever
picks this up later:

- Judge scores need ground-truth anchoring (CI results, revert rate,
  human rewrite rate) or they select for judge-invisible failure modes.
- Routing evidence must come from pairwise comparison on the traffic to be
  migrated, not population scores on the cheap model's own traffic.
- Taxonomy dimensions must be entry-observable and gap-separating, pruned
  by data; prefer routing on known attributes (route, caller,
  batch/interactive, context size) and caller-declared intent first.
- Interactive multi-task sessions are a poor routing target (the human and
  the agent harness are better routers; mid-loop model flips also break
  prompt caching). The realistic Phase 2 market is high-volume uniform
  traffic, which must actually exist before Phase 2 does.
- "$0 local model" is an accounting fiction — cost it at loaded GPU rates.
- Goodhart risk once anything routes on judge scores; keep a frozen
  calibration set re-judged on every rubric/judge change.
