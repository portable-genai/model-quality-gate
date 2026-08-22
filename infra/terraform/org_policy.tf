# org_policy.tf : Org Policy constraints that make residency an ORGANISATION rule, not a
# convention this module happens to follow.
#
# General Principle map:
#   P-03 (residency): `gcp.resourceLocations` is the only control that stops a resource
#         being created outside the reviewed region by a path this Terraform does not own
#         (console, gcloud, another module, a service that provisions on your behalf).
#         var.allowed_regions is the SAME list the app validates at load
#         (config/settings.yaml allowed_regions, model_quality_gate.config.validate_residency) and
#         the same list var.region is checked against at plan time. One list, three
#         enforcement points: plan, org, runtime.
#   P-01 (least surface): service-account key creation is disabled org-wide for this
#         project; workload identity is the only credential path (see iam.tf).
#
# Scope: these are PROJECT-level policies, so a shared org is not reconfigured by applying
# this stack. `var.org_id` remains the parent for Access Context Manager (vpc_sc.tf).
#
# Value-group form: the allowlist entries are `in:<region>-locations` value groups, which
# admit the region plus its own multi-region parents where Google models them. A literal
# region list would reject legitimate in-region resources whose location string differs
# (e.g. a regional bucket reported under its value group).

locals {
  # gcp.resourceLocations takes location VALUE GROUPS, not bare region ids.
  allowed_location_groups = [for r in var.allowed_regions : "in:${r}-locations"]
}

resource "google_org_policy_policy" "resource_locations" {
  count = var.enable_org_policy ? 1 : 0

  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    inherit_from_parent = false

    rules {
      values {
        allowed_values = local.allowed_location_groups
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_org_policy_policy" "disable_sa_key_creation" {
  count = var.enable_org_policy ? 1 : 0

  name   = "projects/${var.project_id}/policies/iam.disableServiceAccountKeyCreation"
  parent = "projects/${var.project_id}"

  spec {
    inherit_from_parent = false

    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}
