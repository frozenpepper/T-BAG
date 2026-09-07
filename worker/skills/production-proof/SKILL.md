---
name: production-proof
description: Design verification that establishes the production mechanism matters rather than merely making helper tests green.
---

# Production-path Proof

Use when acceptance depends on production wiring, regression proof or a mechanism that can be bypassed accidentally.

Identify the production entry point and the mechanism claimed to implement the behavior. Trace the real trigger through the owning mechanism to the observable/durable downstream effect or consumer; do not stop at a helper return value when production correctness depends on later wiring, persistence, reload or another boundary. Establish at least one realistic positive path and, when practical, a negative/counterexample or sensitivity control that would fail if the mechanism were absent, bypassed or wired to the wrong owner. Treat helper/unit tests as local evidence only unless they demonstrably reach the production route.

Do not weaken tests or replace production proof with test-name inspection. Report exactly what surface and denominator were exercised, which production boundaries were actually crossed, and what remains unproven.
