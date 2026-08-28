# variables.tf : The only knobs. Everything else is a concrete in-region value.
#
# General Principle map:
#   P-03 (residency): `region` defaults to asia-southeast1 and is validated against the
#         deployment's reviewed allowlist.
#   P-08 (auditability/retention): `retention_days` is a Terraform variable (the
#         WORM bucket lock is irreversible, so retention must be deliberate).
#
# Per the build contract, ONLY project_id and a couple of genuinely per-tenant
# values (org/billing ids, the VPC-SC toggle) are variables. All service identifiers,
# locations, dataset/bucket names, and template names are concrete.

variable "project_id" {
  description = "Target GCP project id (required)."
  type        = string
}

variable "allowed_regions" {
  description = "Residency-approved deployment regions. Extend only after governance review."
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must contain at least one approved GCP region."
  }
}

variable "region" {
  description = "Deployment region, validated against allowed_regions (P-03)."
  type        = string
  default     = "asia-southeast1"

  validation {
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be present in allowed_regions (P-03)."
  }
}

variable "retention_days" {
  description = "WORM audit-log retention in days. Default ~7 years. Lock is irreversible."
  type        = number
  default     = 2557 # ~7 years; mirrors config/settings.yaml logging.retention_days

  validation {
    condition     = var.retention_days >= 2557
    error_message = "Compliance retention must be at least 2557 days (~7 years) (P-08)."
  }
}

variable "org_id" {
  description = "Organization id : required for Org Policy and Access Context Manager."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (used by Assured Workloads / FinOps tagging)."
  type        = string
  default     = ""
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the org.
    Required when enable_vpc_sc = true; the service perimeter is created under it.
  EOT
  type        = string
  default     = ""
}

variable "enable_vpc_sc" {
  description = "Create the VPC Service Controls perimeter around the AI/data APIs (P-03)."
  type        = bool
  default     = true
}

variable "vpc_sc_enforce" {
  description = <<-EOT
    Enforce the VPC-SC perimeter. FALSE (the default) applies it as an explicit DRY RUN:
    violations are logged, nothing is blocked. Run dry-run first, read the violation logs
    until they are clean, then set this to true. Flipping straight to enforcement on a
    live project locks out callers you did not know about, including your own CI (P-03).
  EOT
  type        = bool
  default     = false
}

variable "enable_org_policy" {
  description = <<-EOT
    Apply the project-level Org Policy constraints (gcp.resourceLocations residency
    allowlist, iam.disableServiceAccountKeyCreation). Requires the caller to hold
    orgpolicy.policyAdmin; set false only for a sandbox where that is not granted.
  EOT
  type        = bool
  default     = true
}

variable "alert_notification_channels" {
  description = <<-EOT
    Monitoring notification channel ids for the residency / perimeter posture alerts
    (posture_alerts.tf). Adopter-owned: an empty list still creates the alert policy, it
    simply has nowhere to send. Format: projects/<id>/notificationChannels/<n>.
  EOT
  type        = list(string)
  default     = []
}
