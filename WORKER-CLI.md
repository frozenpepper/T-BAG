# T-BAG — Worker CLI Routing

Cold-load this router only when CLI-specific launch, resume, storage, failure, or output behavior matters. Parent harness and worker CLI are independent.

Wired technical-worker backends in this release:

- `worker-cli/OPENCODE.md`
- `worker-cli/CODEX.md`

Do not load unrelated CLI files. An unwired CLI is consultant-only until it has an adapter that preserves the lifecycle contract.

**Never bypass `dsd_attempt.py launch` for a technical task.** Every wired backend must preserve budget reservation, frozen checkpoint/scope baseline, attempt record, terminal event, report path, resumable session identity where supported, and arbitrary mid-flight inspection. Launch must return while the worker is running; completion may not be the only observation point.

Universal transport rules:

- process exit never means semantic PASS;
- resume healthy interrupted same-task work when trustworthy; do not preserve a confused frame merely because a session exists;
- log/report growth proves at most liveness, not semantic progress;
- lifecycle identity comes from structured stdout, never merged noisy stderr;
- authorization refusals are findings, not transient transport errors;
- only a harness-owned per-attempt observer may block; the conversational parent may not.
