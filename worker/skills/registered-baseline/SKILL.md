---
name: registered-baseline
description: Gate new conformance regressions while carrying known debt by tracking stable identities instead of only aggregate counts.
---

# Registered Baseline

Use when introducing a conformance gate over known existing debt. Register each known violation by stable identity and preserve enough evidence that identity cannot silently change through sorting, normalization or representation tricks. Reject new unregistered violations and **unexplained disappearance or identity drift** of registered entries. Repairs deliberately shrink the register with explicit evidence. Do not use only an aggregate count as the gate, and prove the gate can detect at least one synthetic/new violation when practical.
