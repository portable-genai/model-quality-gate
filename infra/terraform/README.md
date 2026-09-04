# `model-quality-gate` infrastructure (Terraform)

Regional infrastructure for the `model-quality-gate` Platform. The region defaults
to `asia-southeast1` and must be in the reviewed `allowed_regions` list. Every service id,
location, dataset, and bucket name resolves in-region and matches
[`config/settings.yaml`](../../config/settings.yaml).

> Do not run `terraform apply` against a real project without your own security and
> model-risk sign-off. The WORM bucket lock (`logging_worm.tf`) is **irreversible**.

## What this provisions

| File | Resource | Principle |
|------|----------|-----------|
| `apis.tf` | Enable the managed services `model-quality-gate` uses | P-01 |
| `kms.tf` | Regional CMEK key ring + per-service key bindings | P-03, P-09 |
| `bigquery.tf` | Eval-metrics + model-drift + prompt-version dataset/tables (CMEK) | P-03, P-07, P-09 |
| `cloud_storage.tf` | Golden-dataset + model-card buckets (CMEK, versioned, private) | P-03, P-05, P-07, P-09 |
| `cloudbuild.tf` | The CI promotion gate (runs lint + tests + the eval gate) | P-08 |
| `logging_worm.tf` | Locked WORM audit bucket + sink + data-access audit config | P-03, P-08, P-09 |
| `iam.tf` | Least-privilege service accounts (app, agent runtime, Cloud Build) | P-06 |
| `vpc_sc.tf` | VPC Service Controls perimeter around the AI/data plane | P-01, P-03 |
| `outputs.tf` | Values to wire back into `settings.yaml` after apply | n/a |

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars   # then edit project_id, org_id, ...
terraform init -input=false
terraform plan                                  # review every resource before apply
# terraform apply                               # only with your own sign-off
```

After apply, export the outputs into the runtime environment (or paste into
`config/settings.yaml`):

```bash
export AI_QUALITY_KMS_KEY="$(terraform output -raw kms_key)"
```

## Residency notes

- Region defaults to `asia-southeast1` and is validated against `allowed_regions`; an
  unapproved value fails `terraform plan` (P-03).
- CMEK does **not** cascade (P-09): each service (BigQuery, Cloud Storage, Vertex / Agent
  Platform, Logging) has its own explicit key binding in `kms.tf`.
- The audit bucket is **locked** (WORM) with ~7-year retention (P-08): this is
  irreversible, so confirm `retention_days` before apply.
- The VPC-SC perimeter (`vpc_sc.tf`) is on by default; see the deploy-order caveat in that
  file before enabling it on a project that is not yet provisioned.
