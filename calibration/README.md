# Side-Eye calibration

Frozen yardstick for measuring *judge* quality (the Goodhart meter).

- `calibration_pools.jsonl` — 63 frozen pairs (35 tasks x clean/planted + 5 clean-only controls).
  Planted answers carry exactly one subtle defect; the defect label is hidden from the judge.
  **Never regenerate** — the set must stay frozen for cross-judge comparison.
- `evaluate.py` — grades every pool answer with a strict-JSON verdict, scores recall on
  planted defects + false-flag rate on clean, writes per-judge reports.
- Judge is env-configurable, so any judge on any machine can grade the same frozen pools:
  - local 27B (default): `SIDEEYE_JUDGE_BASE_URL=http://<yos>:11434/v1/chat/completions`
  - Fable: `SIDEEYE_JUDGE_BASE_URL=https://api.anthropic.com/v1/messages SIDEEYE_JUDGE_API_KEY=... \
    SIDEEYE_JUDGE_MODEL=claude-fable-5 SIDEEYE_CALIB_JUDGE_ID=fable-5 python3 evaluate.py`
- Outputs are per-judge: `<judge_id>_verdicts.jsonl` (checkpointed, resumable) +
  `<judge_id>_report.md`. Stop early with `touch STOP`.
- Baseline (27B, 2026-08-30): recall ~74% of judged planted defects (61% incl. 5 unjudged),
  false-flags 7%. Weakness: incorrect-API-claim class (~30% caught).
