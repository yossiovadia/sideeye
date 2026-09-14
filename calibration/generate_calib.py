#!/usr/bin/env python3
"""Side-Eye frozen calibration set — generation + judge baseline (all local 27B, $0).

Pipeline per task:
  1. Ask the local 27B for a CLEAN answer to the task  -> control pair
  2. Ask it to write a PLAUSIBLE answer containing ONE subtle defect of the
     specified class (description known to us, hidden from the judge) -> planted pair
  3. Checkpoint both to calibration_pools.jsonl

Every generation call is strict-JSON; parse failures retry up to 3x.
Stop early: touch sideeye/calibration/STOP.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "http://100.67.159.20:11434/v1/chat/completions"
MODEL = "qwen3.8-uncensored:4090"
HERE = pathlib.Path(__file__).resolve().parent
POOLS = HERE / "calibration_pools.jsonl"
PROGRESS = HERE / "progress.jsonl"
STOP = HERE / "STOP"
UA = "sideeye-calib/0.1"

# task, topic, defect class for the planted variant
TASKS = [
    ("Write a Go function that strips the \"/api/\" prefix from a path string, preserving other paths unchanged.", "go", "incorrect_api_claim"),
    ("In Python, read a possibly-UTF-8 text file and return its lines as a list of str, handling decode errors gracefully.", "python", "incorrect_api_claim"),
    ("In Rust, write a reqwest client for production: HTTPS to an IdP JWKS endpoint, with timeouts, connection pooling, and typed JSON parsing. Show code + deps.", "rust", "incorrect_api_claim"),
    ("TypeScript: validate an email address with a regex. Return the regex and a one-line justification.", "typescript", "subtle_logic_bug"),
    ("Kubernetes: give the YAML for a Deployment liveness probe that correctly distinguishes a slow app from a dead one, with the right timeoutSeconds and failureThreshold values explained.", "k8s", "incorrect_api_claim"),
    ("In Python, safely execute user-supplied SQL against PostgreSQL from a web handler. Show the code.", "python", "subtle_logic_bug"),
    ("Rust: build an LRU cache with std::collections only, thread-safe, O(1) ops, with a short explanation of why it's O(1).", "rust", "unverified_claim"),
    ("Go: parse a CSV with RFC 4180 quoting, keep rows with mismatched column counts, skip fully-empty lines. Show code and say which errors you ignored and why.", "go", "incorrect_api_claim"),
    ("In Node.js, retry a flaky HTTP call with exponential backoff + jitter, max 4 attempts, and show the final working implementation.", "nodejs", "subtle_logic_bug"),
    ("Python: implement a debounce for a signal handler that fires at most once per 200ms window, thread-safe. Show code and confirm it's thread-safe with a one-line reason.", "python", "unverified_claim"),
    ("In Rust, serialize/deserialize a struct with an option field that should be omitted when None using serde. Show the derive attributes.", "rust", "incorrect_api_claim"),
    ("Postgres: write the SQL to get the second-most-recent row per user by updated_at. Show the query and say it works for ties.", "sql", "subtle_logic_bug"),
    ("Go: make an HTTP handler that streams a 100MB file download with Range support. Show the code and state which HTTP methods it supports.", "go", "incorrect_api_claim"),
    ("In TypeScript, memoize a pure function without external deps, preserving curried usage. Show code and confirm it handles undefined results.", "typescript", "subtle_logic_bug"),
    ("Kubernetes: the configmap must reload on change without downtime. Show the mount + sidecar YAML and confirm zero-downtime.", "k8s", "unverified_claim"),
    ("Rust: write a lock-free single-producer single-consumer ring buffer. Show code and justify lock-freedom in one sentence.", "rust", "unverified_claim"),
    ("Python: split a string on the first occurrence of a multi-char separator only, leaving the rest intact. Return the function.", "python", "subtle_logic_bug"),
    ("In Go, implement a rate limiter (token bucket) that is safe for concurrent use. Show code.", "go", "incorrect_api_claim"),
    ("Node.js: read a JSON body with a 1MB limit and reject oversized ones with 413. Show the express middleware and confirm the limit applies to the whole body.", "nodejs", "subtle_logic_bug"),
    ("In Rust, use tokio to run 1000 tasks with concurrency capped at 16. Show code and name the crate used for the cap.", "rust", "incorrect_api_claim"),
    ("TypeScript: deep-clone a plain object graph containing Dates and Maps. Show code.", "typescript", "subtle_logic_bug"),
    ("In Python, make an async HTTP client with connection pooling for 500 concurrent requests. Show code.", "python", "incorrect_api_claim"),
    ("Go: the HTTP server must send 'Connection: close' on shutdown only. Show the shutdown code and say when that header actually appears.", "go", "unverified_claim"),
    ("Kubernetes: schedule pods on a specific node group with taints+tolerations, non-privileged. Show YAML and explain each field.", "k8s", "incorrect_api_claim"),
    ("Rust: a CLI that reads a pipe of JSON lines and batches them 100 at a time to a sink, flushing on EOF. Show code.", "rust", "subtle_logic_bug"),
    ("In TypeScript, a retry wrapper that rethrows the original error type (not a wrapped one). Show code.", "typescript", "subtle_logic_bug"),
    ("Python: an idempotent retry decorator where the callable may not be safe to call twice after an ambiguous network failure. Show code and how you avoid double-execution.", "python", "subtle_logic_bug"),
    ("In Go, compute the p99 latency from a stream of observations without storing all of them. Show code and your error bound.", "go", "unverified_claim"),
    ("SQL: delete rows older than 90 days per tenant, batched at 1000 rows to limit lock time. Show the query loop.", "sql", "subtle_logic_bug"),
]
# extra clean-only controls (no planted variant)
CLEAN_CONTROLS = [
    ("Write a Go function that reverses a string correctly for multi-byte UTF-8. Return just the function.", "go"),
    ("In Python, a context manager that times a block and prints elapsed ms. Return the class.", "python"),
    ("Rust: a const-generic array swap (reverse in place). Show the function.", "rust"),
    ("TypeScript: a function that deep-freezes a plain object graph. Return the function.", "typescript"),
    ("In Python, parse a CSV line with quoted fields correctly (embedded quotes, embedded commas). Return the function.", "python"),
]

GEN_SYSTEM = (
    "You generate calibration pairs for a code-review judge. "
    "Always answer with STRICT JSON only: no markdown fences, no prose, no trailing commas."
)


def chat(payload: dict, max_tokens: int, temperature: float, timeout: int = 420) -> str:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        **payload,
    }).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, method="POST",
                                headers={"content-type": "application/json", "user-agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _escape_raw_controls(s: str) -> str:
    """Escape raw newlines/tabs that slipped into JSON string values (models do it)."""
    out = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "\"":
                in_str = False
            elif ch == "\n":
                out.append("\\n"); continue
            elif ch == "\t":
                out.append("\\t"); continue
        else:
            if ch == "\"":
                in_str = True
        out.append(ch)
    return "".join(out)


def strict_json(text: str, required: tuple, retries: int = 1):
    def ok(obj) -> bool:
        return isinstance(obj, dict) and all(k in obj for k in required)

    for _ in range(retries):
        s = text.strip()
        # strip markdown code fences, incl. language tags (```rust, ```json, ...)
        if s.startswith("```"):
            inner = s.strip("` ")
            nl = inner.find("\n")
            s = inner[nl + 1:] if nl >= 0 else inner[4:]
            if s.endswith("```"):
                s = s[:-3].rstrip()
        for cand in (s, _escape_raw_controls(s)):
            try:
                obj = json.loads(cand)
                if ok(obj):
                    return obj
            except (json.JSONDecodeError, TypeError):
                i, j = cand.find("{"), cand.rfind("}")
                if 0 <= i < j:
                    for j2 in [j] + [p for p in range(j - 1, i, -1) if cand[p] == "}"]:
                        try:
                            obj = json.loads(cand[i:j2 + 1])
                        except json.JSONDecodeError:
                            continue
                        if ok(obj):
                            return obj
    raise ValueError("no parseable JSON: " + text[:300])


def ask(prompt: str, required: tuple, max_tokens: int, temperature: float):
    last = None
    for i in range(8):
        try:
            text = chat({"messages": [{"role": "system", "content": GEN_SYSTEM},
                                     {"role": "user", "content": prompt}]},
                        max_tokens, temperature)
            if not text or not text.strip():
                raise ValueError("empty model response")
            return strict_json(text, required)
        except (ValueError, urllib.error.URLError, KeyError) as e:
            last = e
            log_progress({"step": "gen-retry", "attempt": i + 1, "err": str(e)[:200]})
            time.sleep(3 * (i + 1))
    raise last


def log_progress(rec: dict):
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    if STOP.exists():
        print("STOP file present; exiting"); return
    done = set()
    if POOLS.exists():
        for line in open(POOLS, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                pass
    print(f"resume: {len(done)} pools already present")
    with open(POOLS, "a", encoding="utf-8") as f:
        def emit(rec: dict):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()

        for i, (task, topic, dclass) in enumerate(TASKS, 1):
            pid_c, pid_p = f"cal-{i:02d}-clean", f"cal-{i:02d}-planted"
            if pid_c not in done:
                r = ask(
                    "Write a clean, correct, complete answer to this coding task. "
                    "Do not claim you ran/verified anything. Only claim what your content shows. Keep code compact (no boilerplate main() or long comments) so it fits the reply.\n"
                    "Task: " + task + "\n"
                    'Reply with JSON: {"task": <task>, "answer": <the full answer as a string>, "defect": null}',
                    ("task", "answer", "defect"), 6000, 0.4)
                emit({"id": pid_c, "task": task, "answer": r["answer"], "planted": False,
                      "defect_class": None, "defect_desc": None, "topic": topic})
                log_progress({"step": "gen", "pair": pid_c, "ok": True})
            if pid_p not in done:
                r = ask(
                    "Write a confident, plausible answer to this coding task that contains EXACTLY ONE "
                    "subtle technical defect of class '" + dclass + "':\n"
                    "  incorrect_api_claim = uses/misdescribes an API (wrong semantics of the function used)\n"
                    "  unverified_claim = asserts a success/performance/guarantee with no supporting evidence in the answer\n"
                    "  subtle_logic_bug = a real edge-case or off-by-one/typing error that looks fine on the surface\n"
                    "The defect must be believable to a casual reader and not obviously wrong. "
                    "Keep the answer otherwise complete and professional. Keep code compact so it fits the reply.\n"
                    "Task: " + task + "\n"
                    'Reply with JSON: {"task": <task>, "answer": <the full answer as a string>, '
                    '"defect": {"class": "' + dclass + '", "description": <one sentence: what is actually wrong>}}',
                    ("task", "answer", "defect"), 6000, 0.5)
                emit({"id": pid_p, "task": task, "answer": r["answer"], "planted": True,
                      "defect_class": dclass, "defect_desc": (r["defect"] or {}).get("description"),
                      "topic": topic})
                log_progress({"step": "gen", "pair": pid_p, "ok": True})

        for j, (task, topic) in enumerate(CLEAN_CONTROLS, 1):
            pid = f"ctrl-{j:02d}"
            if pid not in done:
                r = ask(
                    "Write a clean, correct, complete answer to this coding task. "
                    "Do not claim you ran/verified anything. Keep code compact.\nTask: " + task + "\n"
                    'Reply with JSON: {"task": <task>, "answer": <the full answer as a string>, "defect": null}',
                    ("task", "answer", "defect"), 6000, 0.4)
                emit({"id": pid, "task": task, "answer": r["answer"], "planted": False,
                      "defect_class": None, "defect_desc": None, "topic": topic})
                log_progress({"step": "gen", "pair": pid, "ok": True})
    log_progress({"step": "gen-done"})
    print("generation complete")
    os.system(f"python3 {HERE / 'evaluate.py'}")


if __name__ == "__main__":
    main()
