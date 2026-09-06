# Compliance FAQ

## Is the reference mapping regulator approval?

No. `COMPLIANCE.md` is engineering traceability. Each adopter owns the regulatory
crosswalk, legal interpretation, control owner, evidence acceptance, and change approval
(the open G2 audit item).

## Which evidence should be retained?

Retain the exact target, dataset/version, metric bundle, per-metric and probe results,
eligibility verdict, model card, reviewer disposition, and release linkage according to
the institution's approved schedule.

## How do sibling systems divide responsibility?

`enterprise-knowledge-base` governs reference knowledge, `agent-registry` discovery, `agent-observability` durable audit, `human-review-console` human
review/disposition, and `agent-guardrail-gateway` runtime guardrails. `model-quality-gate` owns only pre-promotion evaluation,
red-team eligibility, and MRM evidence.
