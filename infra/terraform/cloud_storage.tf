# cloud_storage.tf : Golden-dataset + model-card buckets (CMEK, in-region).
#
# General Principle map:
#   P-03 (residency): both buckets are single-region us-central1.
#   P-05 (private-only data plane): uniform bucket-level access + public access
#         prevention, so neither bucket can be made public.
#   P-09 (CMEK explicit): each bucket's default_kms_key_name is the regional key
#         (CMEK does not cascade : Cloud Storage needs its own key binding).
#   P-07 (model-risk evidence): the model-cards bucket is versioned, so a card's
#         history is retained as MRM evidence.

resource "google_storage_bucket" "golden_datasets" {
  name     = "ai-quality-golden-datasets" # matches settings.yaml storage.golden_bucket
  project  = var.project_id
  location = var.region # us-central1 (P-03)

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced" # P-05 : never public

  encryption {
    default_kms_key_name = google_kms_crypto_key.model_quality_gate.id # CMEK explicit (P-09)
  }

  versioning {
    enabled = true
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.storage,
  ]
}

resource "google_storage_bucket" "model_cards" {
  name     = "ai-quality-model-cards" # matches settings.yaml storage.model_cards_bucket
  project  = var.project_id
  location = var.region # us-central1 (P-03)

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.model_quality_gate.id
  }

  # Retain model-card history as MRM evidence (P-07).
  versioning {
    enabled = true
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.storage,
  ]
}

# Immutable, run-keyed promotion artifacts are separated from the mutable model-card
# index. Retention is locked at creation; the runtime has create/read but no delete role.
resource "google_storage_bucket" "mrm_evidence" {
  name     = "ai-quality-mrm-evidence"
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.model_quality_gate.id
  }

  retention_policy {
    retention_period = var.retention_days * 86400
    is_locked        = var.evidence_bucket_locked
  }

  versioning {
    enabled = true
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.storage,
  ]
}
