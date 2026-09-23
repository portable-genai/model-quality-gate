# logging_worm.tf : WORM audit trail: lockable Cloud Logging bucket + sink + audit config.
#
# General Principle map:
#   P-08 (immutable audit / WORM): the audit log is routed to a Cloud Logging bucket
#         whose retention is var.retention_days (~7 years) and whose lock (var.worm_locked)
#         makes it Write-Once-Read-Many. The audit adapter (cloud_logging_audit)
#         writes every gate / eval / red-team AuditEvent here.
#   P-03 (residency): bucket location is us-central1.
#   P-09 (CMEK explicit): the bucket is CMEK-encrypted (logging SA key binding in kms.tf).
#
# ############################################################################ #
# # WARNING : LOCKING IS IRREVERSIBLE.                                        # #
# # Setting worm_locked = true permanently prevents reducing retention or     # #
# # deleting this bucket for the full retention window. You CANNOT undo it,   # #
# # not even with project-owner rights. Confirm retention_days before apply.  # #
# # No default: state worm_locked. false keeps it deletable (NOT for prod).   # #
# ############################################################################ #

resource "google_logging_project_bucket_config" "worm_audit" {
  project        = var.project_id
  location       = var.region        # us-central1 (P-03)
  bucket_id      = "ai-quality-worm" # matches settings.yaml logging.bucket
  description    = "WORM audit bucket for model-quality-gate (lockable, ~7y retention)."
  retention_days = var.retention_days # 2557 (~7 years) by default

  # IRREVERSIBLE when true (see the warning banner above), and never defaulted.
  locked = var.worm_locked

  # CMEK on the log bucket (P-09) : explicit, does not cascade.
  dynamic "cmek_settings" {
    for_each = var.cmek_enabled ? [1] : []
    content {
      kms_key_name = one(google_kms_crypto_key.model_quality_gate[*].id)
    }
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.logging,
  ]
}

# Route the audit log stream into the WORM audit bucket.
resource "google_logging_project_sink" "audit_to_worm" {
  project     = var.project_id
  name        = "ai-quality-audit-to-worm"
  description = "Routes the ai-quality-audit log to the WORM audit bucket."

  destination = "logging.googleapis.com/${google_logging_project_bucket_config.worm_audit.id}"

  # Capture this service's audit log only. Cloud Audit Logs are NOT copied here: _Default already keeps them.
  filter = <<-EOT
    logName="projects/${var.project_id}/logs/ai-quality-audit"
  EOT

  unique_writer_identity = true
}

# --------------------------------------------------------------------------- #
# Enable Data Access audit logs (DATA_READ) so every read of the eval metrics,
# golden datasets, and the audit store itself is audited (P-08). ADMIN_READ and
# DATA_WRITE are on by default; we add DATA_READ explicitly.
# --------------------------------------------------------------------------- #
resource "google_project_iam_audit_config" "data_access" {
  count   = var.manage_audit_config ? 1 : 0
  project = var.project_id
  service = "allServices"

  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
  audit_log_config {
    log_type = "ADMIN_READ"
  }
}
