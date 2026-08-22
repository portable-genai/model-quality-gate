# Adoption FAQ

## Should we fork Hrz4?

Usually no. Consume one governed service so model-risk policy and evidence remain
consistent. Fork when your institution needs independent policy and release authority.

## How do we add a provider?

Implement the relevant typed ports, add explicit profile bindings, and extend the
constructor, behavioral, and portability contract tests. Never add a managed fallback.

## What stays institution-owned?

Golden datasets, bundle approval, threshold changes, evaluator validation, region and key
custody, identity, sibling endpoints, Hrz7 review routing, operations, and releases.

See [the adoption guide](../ADOPTING.md).
