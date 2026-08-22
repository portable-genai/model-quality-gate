# Portability FAQ

## What does `make portability-demo` prove?

It proves the declared 13-port profile matrix, lazy construction of managed/delegate
adapters without network calls, two identical isolated local gate runs, local audit-chain
validity, fail-fast on-prem evaluation, and rejection of unknown profiles.

## What does it not prove?

It does not call live GCP, IAP, Hrz2, Hrz3, or Hrz5; complete on-prem adapters; migrate
managed storage; port identity-provider or tenant authorization; or prove infrastructure,
UI/channel, policy, or regulator portability.

## Why does an unknown profile fail?

Silent fallback could route sensitive evaluation data to the wrong provider. Every port
binding for an unknown profile is rejected. The named `platform` profile is the sole
documented hybrid: identity plus Hrz2/Hrz3/Hrz5 delegates are explicit and its other ports
retain their managed GCP adapters.
