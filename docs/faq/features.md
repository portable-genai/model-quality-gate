# Features FAQ

## Does a PASS deploy or promote the model?

No. PASS means the tested target is eligible under the selected bundle. The deployment
pipeline and any Hrz7 maker-checker approval remain outside Hrz4.

## Who should use the evidence?

Model-risk officers inspect per-metric results, adversarial probes, the model card, caveats,
and immutable references. MLOps consumes the verdict but must not infer authorization to
deploy.

## Does Hrz4 replace runtime guardrails?

No. Hrz1 remains the runtime safety control. Hrz4 evaluates a versioned target before
promotion.
