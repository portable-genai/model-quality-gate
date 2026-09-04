# `model-quality-gate` FAQs

- [Features and model-risk ownership](features.md)
- [Security and identity](security.md)
- [Portability and exit](portability.md)
- [Adoption and forking](adoption.md)
- [Compliance and evidence](compliance.md)

| Role | Start with |
|---|---|
| Model-risk officer / approver | [Features](features.md), then [compliance evidence](compliance.md) |
| Security / identity owner | [Security and identity](security.md) |
| Platform / MLOps engineer | [Adoption](adoption.md), then [portability](portability.md) |
| Auditor / compliance owner | [Compliance evidence](compliance.md), then [security](security.md) |

`model-quality-gate` owns the deterministic evaluation/red-team eligibility verdict and its MRM evidence.
`enterprise-knowledge-base` owns governed reference knowledge, `agent-registry`, `agent-observability` durable cross-service
audit, `human-review-console` human disposition, and `agent-guardrail-gateway` runtime safety controls.
