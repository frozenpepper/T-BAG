---
name: positive-control
description: Prove an audit or detector is sensitive by including a known detectable violation or input when practical.
---

# Positive Control

Use when a check could appear green merely because it is insensitive. When practical, perform an explicit **break → observe RED → restore → observe GREEN** cycle, or an equivalent known-detectable condition. The broken condition must exercise the claimed mechanism rather than an unrelated syntax/setup failure. Restore the exact intended state and rerun the real check. Report what the control proves, what it does not, and any surface that still lacks sensitivity evidence.
