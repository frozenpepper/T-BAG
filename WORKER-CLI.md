# T-BAG — Worker CLI Routing

Cold-load this router only when CLI-specific launch, resume, storage, failure, or output behavior matters. Parent harness and worker CLI are independent.

Wired technical-worker backends in this release:

- `worker-cli/OPENCODE.md`
- `worker-cli/OPENCODE2.md`
- `worker-cli/CODEX.md`
- `worker-cli/CLAUDE.md`

Do not load unrelated CLI files. These adapters are **pre-wired optimizations**, not the semantic capability boundary of the skill: a capable parent may satisfy an unusual owner-requested CLI/tool path when it can preserve the T-BAG lifecycle contract. Repeated/common mechanisms should graduate into an adapter instead of being rediscovered every run.

**Never bypass `dsd_attempt.py launch` for a technical task.** Every wired backend must preserve budget reservation, frozen checkpoint/scope baseline, attempt record, terminal event, report path, resumable session identity where supported, and arbitrary mid-flight inspection. Launch must return while the worker is running; completion may not be the only observation point.

Universal transport rules:

- process exit never means semantic PASS;
- resume healthy interrupted same-task work when trustworthy; do not preserve a confused frame merely because a session exists;
- log/report growth proves at most liveness, not semantic progress;
- lifecycle identity comes from structured stdout, never merged noisy stderr;
- authorization refusals are findings, not transient transport errors;
- only a harness-owned per-attempt observer may block; the conversational parent may not.
