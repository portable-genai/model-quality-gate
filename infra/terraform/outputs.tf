# outputs.tf : Values the app/operators need to wire settings.yaml after apply.
#
# These map 1:1 onto config/settings.yaml / config.py fields so a deploy is just
# "apply, then export these into the runtime environment".

output "project_id" {
  description = "The deployment project id."
  value       = var.project_id
}

output "region" {
  description = "Allowlist-validated deployment region."
  value       = var.region
}

# --------------------------------- KMS -------------------------------------- #
output "kms_key" {
  description = "Regional CMEK crypto key id (settings.yaml kms_key / AI_QUALITY_KMS_KEY)."
  value       = google_kms_crypto_key.model_quality_gate.id
}

# ------------------------------- BigQuery ----------------------------------- #
output "bigquery_dataset" {
  description = "Eval metrics + drift dataset id (settings.yaml bigquery.dataset)."
  value       = google_bigquery_dataset.model_quality_gate.dataset_id
}

output "bigquery_location" {
  description = "Confirms BigQuery residency : must be us-central1 (fail-fast)."
  value       = google_bigquery_dataset.model_quality_gate.location
}

# ------------------------------ Cloud Storage ------------------------------- #
output "golden_datasets_bucket" {
  description = "Golden-dataset bucket (settings.yaml storage.golden_bucket)."
  value       = google_storage_bucket.golden_datasets.name
}

output "model_cards_bucket" {
  description = "Model-cards bucket (settings.yaml storage.model_cards_bucket)."
  value       = google_storage_bucket.model_cards.name
}

output "mrm_evidence_bucket" {
  description = "Retention-locked run evidence bucket (settings.yaml storage.mrm_evidence_bucket)."
  value       = google_storage_bucket.mrm_evidence.name
}

# ------------------------------- WORM logging ------------------------------- #
output "log_bucket" {
  description = "Locked WORM audit log bucket id (settings.yaml logging.bucket)."
  value       = google_logging_project_bucket_config.worm_audit.id
}

output "audit_sink_writer_identity" {
  description = "Sink writer identity (grant it bucket access if cross-project)."
  value       = google_logging_project_sink.audit_to_worm.writer_identity
}

# ------------------------------ Cloud Build --------------------------------- #
output "promotion_gate_trigger" {
  description = "The CI promotion-gate Cloud Build trigger id (P-08)."
  value       = google_cloudbuild_trigger.promotion_gate.id
}

# ----------------------------- Service accounts ----------------------------- #
output "app_service_account" {
  description = "Serving/API service account email."
  value       = google_service_account.app.email
}

output "agent_runtime_service_account" {
  description = "Agent Runtime (reasoningEngine) service account email."
  value       = google_service_account.agent_runtime.email
}

output "cloudbuild_service_account" {
  description = "CI promotion-gate Cloud Build service account email."
  value       = google_service_account.cloudbuild.email
}
