# vpc_sc.tf : VPC Service Controls perimeter around the AI/data plane.
#
# General Principle map:
#   P-03 (residency + exfiltration control): a service perimeter draws a logical
#         boundary around the sovereignty-critical APIs (Vertex/Agent Platform +
#         Gen AI evaluation service, BigQuery, Cloud Storage, Logging, KMS, Secret
#         Manager). Data cannot be read across the boundary to an unapproved
#         project, which is what stops the eval metrics, golden datasets, model cards
#         and audit log from leaving the country.
#   P-01 (least surface): only the services A4 uses are inside the perimeter.
#
# Guarded by var.enable_vpc_sc so non-prod/dev applies can skip it (count = 0), and
# DRY-RUN FIRST by default (var.vpc_sc_enforce = false): the perimeter is applied as an
# explicit dry-run spec that logs violations without blocking anything. Only after the
# violation logs are clean should an operator set vpc_sc_enforce = true.
#
# DEPLOY-ORDER CAVEAT:
#   An ENFORCED perimeter blocks API calls from outside it. Enable enforcement AFTER the
#   other resources are created and your Terraform / CI identity is added to an access
#   level, or the apply will be denied. Recommended order:
#     1. Apply everything with enable_vpc_sc = false.
#     2. Apply with enable_vpc_sc = true, vpc_sc_enforce = false (dry run) and read the
#        violation logs until nothing legitimate is being denied.
#     3. Add your operator/CI identity to an access level.
#     4. Re-apply with vpc_sc_enforce = true to enforce the boundary.

locals {
  perimeter_restricted_services = [
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
  ]
}

resource "google_access_context_manager_service_perimeter" "model_quality_gate" {
  count = var.enable_vpc_sc ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/model_quality_gate_sg"
  title  = "model_quality_gate_sg"

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  # Dry-run first: with use_explicit_dry_run_spec the `spec` block is evaluated in
  # audit-only mode. `status` (the enforced config) is created only once an operator has
  # deliberately set vpc_sc_enforce = true.
  use_explicit_dry_run_spec = !var.vpc_sc_enforce

  dynamic "spec" {
    for_each = var.vpc_sc_enforce ? [] : [1]
    content {
      resources           = ["projects/${data.google_project.this.number}"]
      restricted_services = local.perimeter_restricted_services

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  dynamic "status" {
    for_each = var.vpc_sc_enforce ? [1] : []
    content {
      # Confine the project's sovereignty-critical APIs to this perimeter.
      resources           = ["projects/${data.google_project.this.number}"]
      restricted_services = local.perimeter_restricted_services

      # Allow VPC-internal use of every restricted API from inside the boundary.
      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  depends_on = [google_project_service.required]
}
