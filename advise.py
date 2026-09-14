#!/usr/bin/env python3
"""Side-Eye ADVISE — a quick second opinion on the last exchange.

The scoped sibling of `escalate`: instead of the WHOLE session, it sends the last
N user->assistant exchanges (--turns) plus their evidence — tool results and the
git diff of files touched IN those exchanges — to the strong judge and prints a
free-form recommendation. This is the `/escalate-last` surface: "is my recent
change / decision sound?" It's sighted (sees the recent code), but recent-scoped
so it stays far cheaper than a full-session review. --no-code drops the diff for
a pure judgement call ("SQLite or JSONL?") where no code was written yet.

Like escalate, the judge MUST hit the real Claude route, never the cheap model:
the chain in config.py (flag > SIDEEYE_JUDGE_* env > config file > ambient
ANTHROPIC_*) resolves it, and the cheap-route guards reject anything that looks
like this session's own route — the exact self-grading failure this tool exists
to catch.

  python -m sideeye.advise --current --question "SQLite or JSONL for verdicts?"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sideeye.adapters import latest_session, load_transcript, resolve_current_session  # noqa: E402
from sideeye.config import RouteError, require_judge_route  # noqa: E402
from sideeye.judge.code_artifact import build_code_artifact  # noqa: E402
from sideeye.judge.judge import (  # noqa: E402
    advise as run_advise,
    build_advice_body,
    context_guard,
    estimate_cost,
    load_rubric,
    resolve_model,
)
from sideeye.judge.transcript import recent_exchanges  # noqa: E402

# Edit/Write tool_use renders as "[Edit: <path>]" etc. (adapters/claude_code.py);
# used to scope the diff to files touched in the shown exchanges.
_EDIT_REF = re.compile(r"\[(?:Edit|Write|MultiEdit|NotebookEdit): (.+?)\]")

REPO = pathlib.Path(__file__).resolve().parent
DEFAULT_RUBRIC = REPO / "rubric" / "rubric_advice_v1.md"
DEFAULT_OUT = REPO / "verdicts" / "advice.jsonl"
ADVICE_MODEL = "claude-fable-5"      # advice is human-bounded + tiny; use the top tier
DEFAULT_MAX_COST = 1.50              # sighted now (recent diff); still recent-scoped + bounded
_ADVISE_UA = "sideeye-advise"       # metering "client" label for escalate-last traffic


def fail(msg):
    from sideeye.judge import style
    print(style.render_error(msg), file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Side-Eye advise (quick second opinion)")
    ap.add_argument("--question", default="", help="the judgement call you want an opinion on")
    ap.add_argument("--turns", type=int, default=1,
                    help="how many recent user->assistant exchanges to include (default 1); "
                         "raise it when the judgement call spans the last few turns")
    ap.add_argument("--current", action="store_true",
                    help="use the current project's latest session (default behavior; "
                         "explicit for the skill surface)")
    ap.add_argument("--rollout", default=None, help="a specific session file")
    ap.add_argument("--client", choices=("claude", "codex"), default="claude")
    ap.add_argument("--all-projects", action="store_true",
                    help="search every project for the latest session (default: current project)")
    ap.add_argument("--project", default=None, help="a specific project dirname under ~/.claude/projects/")
    ap.add_argument("--model", default=ADVICE_MODEL)
    ap.add_argument("--no-code", action="store_true",
                    help="skip the code diff — pure conversation-only opinion (for judgement "
                         "calls like 'SQLite or JSONL?' where no code was written)")
    ap.add_argument("--repo", default=None, help="repo root for the code diff (default: cwd)")
    ap.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST,
                    help="abort if the estimated cost exceeds this (safety ceiling)")
    ap.add_argument("--yes", action="store_true", help="(compat) advise never prompts; accepted and ignored")
    # Judge route: chain + guards in config.py; --base-url overrides everything.
    ap.add_argument("--base-url", default=None,
                    help="judge route override; default resolves from "
                         "SIDEEYE_JUDGE_* env, the sideeye config file, or ANTHROPIC_*")
    args = ap.parse_args()
    args.model = resolve_model(args.model)   # accept fable/opus/sonnet aliases

    try:
        args.base_url, api_key, _route_source = require_judge_route(args.base_url)
    except RouteError as e:
        fail(str(e))

    # Session selection: default = this project's latest session (so advise
    # reviews the session you're in, not a coin flip across all live sessions).
    if args.rollout:
        rollout = pathlib.Path(args.rollout)
    elif args.all_projects:
        rollout = latest_session(args.client, scope="all")
    elif args.project:
        rollout = latest_session(args.client, scope=args.project)
    else:  # --current or default — robust to a drifted shell cwd
        rollout, fell_back = resolve_current_session(args.client)
        if fell_back and rollout:
            print(f"(cwd has no {args.client} session; using the most recently "
                  "active session instead)")
    if not rollout or not rollout.exists():
        fail(f"no {args.client} session found (run from the session's project dir, "
             "or pass --rollout / --all-projects)")

    transcript = load_transcript(rollout)
    if transcript is None:
        fail(f"no usable turns in {rollout}")

    produced = recent_exchanges(transcript, args.turns, include_tools=True)

    # Sighted advice: append the git diff of files touched IN these recent
    # exchanges (scoped by the edit-refs in the shown turns), so a 2-turn advice
    # reviews the recent change's code — and stays cheap because it's the recent
    # diff, not the whole session's. --no-code skips it for pure judgement calls.
    n_code_files = 0
    if not args.no_code:
        edited = set(_EDIT_REF.findall(produced))
        recent_touched = [tf for tf in (transcript.get("touched_files") or [])
                          if tf["path"] in edited]
        if recent_touched:
            repo_root = pathlib.Path(args.repo) if args.repo else pathlib.Path.cwd()
            diff = build_code_artifact(recent_touched, repo_root)
            if diff:
                produced = produced + "\n\n" + diff
                n_code_files = len(recent_touched)
    rubric_text = load_rubric(args.rubric)

    # Cost ceiling: input count is exact (count_tokens on the real payload);
    # abort before spending if it somehow exceeds the ceiling.
    body = build_advice_body(rubric_text, args.question, produced, model=args.model)
    input_tokens, est_cost, exact, _ = estimate_cost(args.base_url, api_key, body, args.model,
                                                      user_agent=_ADVISE_UA)
    # Hard context-window guard (see escalate.py): refuse a packet that would 400
    # and still be metered. Advice packets are tiny, so this only trips on a bug.
    if (prob := context_guard(input_tokens, args.model, max_tokens=body["max_tokens"])):
        fail(prob)
    if est_cost > args.max_cost:
        fail(f"estimated ${est_cost:.4f} exceeds --max-cost ${args.max_cost:.2f} "
             f"({input_tokens:,} input tokens). Re-run with --max-cost to override.")

    print("sideeye · advice mode")
    scope = "last exchange" if args.turns <= 1 else f"last {args.turns} exchanges"
    code_note = f" + {n_code_files} file(s) diff" if n_code_files else ""
    print(f"  packet: {scope}{code_note} ({input_tokens:,} tokens{'' if exact else ', est'}) "
          f"-> judge: {args.model}")
    print("  route: metered praxis gateway\n")

    try:
        text, meta = run_advise(args.question, produced, rubric_text,
                                base_url=args.base_url, api_key=api_key, model=args.model,
                                user_agent=_ADVISE_UA)
    except Exception as exc:  # noqa: BLE001
        fail(f"judge call failed: {exc}")

    record = {
        "session_id": transcript["session_id"],
        "source": "advice",
        "question": args.question,
        "advice": text,
        "judge_model": meta["judge_model"],
        "judge_input_tokens": meta["input_tokens"],
        "judge_output_tokens": meta["output_tokens"],
        "judge_cost_usd": meta["cost_usd"],
        "judged_at": int(time.time()),
    }
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as out:
        out.write(json.dumps(record) + "\n")

    from sideeye.judge import style
    print("SECOND OPINION")
    print(style.render_advice(text))
    print(f"\n  judge cost: ${meta['cost_usd']:.4f}  ->  {out_path}")


if __name__ == "__main__":
    main()
