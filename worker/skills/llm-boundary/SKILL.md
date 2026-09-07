---
name: llm-boundary
description: Diagnose structured LLM/provider/parser failures from the actual request through first production divergence.
---

# LLM Boundary Diagnostics

Use only for tasks whose evidence crosses an LLM/provider/structured-output boundary.

Trace the real production path in order: rendered request/context and schema expectations; provider/model/endpoint configuration; raw response and exact returned type; finish/stop reason and usage/transport metadata; deserialization/structured-output adapter; production parser/validator; first point where observed data diverges from expected data.

Do not infer the cause from the final exception alone. Preserve raw evidence before repair. Distinguish provider/transport truncation, empty output, schema mismatch, adapter coercion and parser defects. Form at least the credible competing boundary hypotheses and use the smallest discriminating experiment/evidence to eliminate them until the **first production divergence** is established. Check whether retry/resume, streaming/non-streaming, generated client/schema versions or configuration can change that boundary when relevant. Corpus-specific semantic filters, regex patches and output post-processing are not substitutes for establishing the actual boundary failure.
