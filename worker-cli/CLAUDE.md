# T-BAG worker CLI — Claude Code

Cold-load only when the configured technical worker uses Claude Code. Normal task execution goes through `dsd_attempt.py`; direct `claude` calls are outside the recorded T-BAG lifecycle.

## Adapter contract

T-BAG uses Claude Code non-interactive print mode with stream-JSON output. The adapter uses `acceptEdits` plus explicit common agent tools, avoiding dependence on optional Auto mode. It preserves worker-budget reservation, frozen workspace/scope baseline, report/terminal evidence and resumable session identity. The attempt directory is added so the worker can maintain its report while the assigned project view remains the technical surface. A configured runtime `effort` is passed through Claude's native per-session `--effort` flag.

## Resume

Claude print-mode sessions can be resumed by recorded session ID. Resume only healthy interrupted same-role work whose task/authority basis remains valid. Fresh Review and Phase Audit remain fresh even when a prior session exists. A new T-BAG attempt is always recorded around the resumed Claude session.

## Stream boundary

Structured stdout is lifecycle evidence; stderr stays separate. T-BAG extracts `session_id` only from stream-JSON. Process exit, token activity or a valid session ID never means semantic PASS.
