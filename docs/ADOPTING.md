# Adopting Hrz4

Hrz4 is a shared model-risk authority. Most institutions should consume one governed Hrz4
deployment rather than fork it. Fork only when an institution needs an independently
owned promotion policy, release cadence, or evidence boundary.

## Choose the adoption mode

| Mode | Use when | Institution owns |
|---|---|---|
| Consume the API | One model-risk function governs many applications | Golden datasets, approved bundles, service identity, Hrz7 review routing |
| Implement adapters | The domain contract is right but a provider or sibling endpoint differs | New port adapters, credentials, endpoint controls, conformance tests |
| Fork and rename | The institution needs independent source and release authority | All operations, security, policy, evidence retention, and upstream merges |

The stable seams are the domain artifacts, gate API, and 13 typed ports. The institution
must review evaluator and red-team adapters, golden data, identity and service-to-service
controls, region/CMEK/retention, Hrz2/Hrz3/Hrz5 endpoints, Hrz7 disposition, thresholds,
and evidence approval. Thresholds remain code constants today; they are not config-tunable
(the open B4 audit item).

Hrz4 returns model promotion eligibility and evidence. It never deploys a model or
substitutes for the institution's maker-checker approval.

## Mechanical rename

Preview first:

```bash
python scripts/rename_fork.py \
  --package bank_model_gate \
  --cli bank-quality \
  --service bank-model-risk \
  --distribution bank-model-risk \
  --env-prefix BANK_QUALITY
```

Repeat with `--yes` to apply. The tool validates every name and destination before writing,
uses longest-first replacements, renames package paths, and formats the result. It skips
Git state, virtual environments, generated state, and `.agents/skills`: those are canonical
upstream build skills, not application source to rewrite.

The rename does not migrate local SQLite files, cloud resources, secrets, IAM, DNS,
identity-provider registrations, or remote datasets. Recreate the environment, regenerate
locks when dependencies change, and run:

```bash
make check
make rename-selftest
```

When taking an upstream update, merge into a branch, resolve only
institution-owned adapters/policy, and rerun both gates before release.

## Adopter-owned files

These files are yours after a fork. Upstream ships each as a filled-in template so the shape
is unambiguous; an upstream merge must never silently overwrite your version of them.

| File / section | What you own |
|---|---|
| `COMPLIANCE.md` > "Regulator crosswalk (ADOPTER-OWNED)" | The rows for YOUR home regulator. Upstream fills it in for MAS (Singapore) as the worked example. |
| `config/settings.yaml` > `policy:` | The promotion bars and the maker-checker borderline band. Shipped values equal the reference constants; retuning one is a governance decision, not an engineering change. |
| `config/settings.yaml` > `allowed_regions` and `infra/terraform` `var.allowed_regions` | The residency allowlist. Extend BOTH, and only after governance review. |
| `infra/terraform/terraform.tfvars` | Project, org, billing, access-policy ids, `vpc_sc_enforce`, and the alert notification channels. |
| `eval/datasets/`, `eval/rubrics/` | Your golden data. The shipped sets are synthetic and are not a validation corpus. |
