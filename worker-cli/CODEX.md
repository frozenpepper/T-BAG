# T-BAG worker CLI — Codex

Cold-load only when the configured technical worker uses Codex. Normal task execution goes through `dsd_attempt.py`; direct `codex exec` is outside the T-BAG lifecycle.

## Adapter contract

T-BAG uses Codex JSONL execution while preserving worker-budget reservation, task baseline/scope evidence, report/terminal records, separate stdout/stderr, and resumable thread identity.

Mutating roles run with the assigned task worktree as their working project surface and the attempt directory writable for reports. Read-only roles write from the attempt directory while the rendered prompt names the frozen project view explicitly. Do not reproduce the transport command by hand; the adapter owns current sandbox/working-directory details.

A configured runtime `effort` is passed through as Codex `model_reasoning_effort` for that worker session.

## Resume

Resume the recorded thread only for healthy interrupted same-role work whose authority/task basis remains valid. A new T-BAG attempt/report still records the continuation. Do not preserve a confused or non-converging frame merely because a thread ID exists.

## JSONL boundary

Codex stdout is a protocol surface; stderr remains separate. T-BAG extracts resumable identity only from the structured stdout thread-start event and fails visibly if it cannot recover one. Never merge stderr into that parser: diagnostics may contain JSON-looking text.

Process exit or a valid thread ID is transport evidence only. Semantic completion still comes from the worker report, objective gate, and assigned Review lifecycle.
