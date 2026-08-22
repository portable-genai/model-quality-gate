# Security FAQ

## Can callers assert their own actor?

Production identity is verified at the service boundary. Local seeded personas exist only
for offline demonstration. Institutions own IdP/IAP configuration, service identity, IAM,
approved origins, and authorization policy.

## Where does durable audit live?

The local profile uses a tamper-evident hash chain for conformance. Production delegates
durable cross-service audit to Hrz5 or its approved equivalent and must enforce retention,
access, and key controls.

## Is synthetic demo data production-safe?

It contains no customer data, but its successful result is reference evidence only. It
does not validate production identities, networks, datasets, or cloud configuration.
