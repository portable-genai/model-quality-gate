# Features FAQ

## Does a PASS deploy or promote the model?

No. PASS means the tested target is eligible under the selected bundle. The deployment
pipeline and any `human-review-console` maker-checker approval remain outside `model-quality-gate`.

## Who should use the evidence?

Model-risk officers inspect per-metric results, adversarial probes, the model card, caveats,
and immutable references. MLOps consumes the verdict but must not infer authorization to
deploy.

## Does `model-quality-gate` replace runtime guardrails?

No. `agent-guardrail-gateway` remains the runtime safety control. `model-quality-gate` evaluates a versioned target before
promotion.
