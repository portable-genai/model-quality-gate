# kms.tf : Regional Customer-Managed Encryption Keys (CMEK) in Singapore.
#
# General Principle map:
#   P-09 (CMEK does NOT cascade): a CMEK on one resource does not automatically
#         protect data that resource hands to another service. Each managed
#         service (BigQuery, Cloud Storage, Vertex/Agent Platform, Logging) must be
#         told to use this key explicitly. We keep ONE regional key ring + crypto key
#         here and wire it into every resource that supports CMEK in its own file.
#   P-03 (residency): the key ring location is us-central1 : a regional key,
#         never the global/multi-region key. Regional CMEK pins crypto material in-country.

resource "google_kms_key_ring" "model_quality_gate" {
  name     = "ai-quality-ring"
  location = var.region # us-central1 : regional, in-country key material (P-03)

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "model_quality_gate" {
  name     = "ai-quality-cmek"
  key_ring = google_kms_key_ring.model_quality_gate.id

  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = "7776000s" # 90 days : periodic rotation for key hygiene

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE"
  }

  lifecycle {
    # A destroyed key is unrecoverable and would strand all CMEK-encrypted data.
    prevent_destroy = true
  }
}

# --------------------------------------------------------------------------- #
# Grant each service agent the right to use the key. CMEK does not cascade
# (P-09): every service that encrypts with this key needs its OWN binding here.
# --------------------------------------------------------------------------- #
data "google_project" "this" {
  project_id = var.project_id
}

# BigQuery service agent (eval metrics + drift datasets).
resource "google_kms_crypto_key_iam_member" "bigquery" {
  crypto_key_id = google_kms_crypto_key.model_quality_gate.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:bq-${data.google_project.this.number}@bigquery-encryption.iam.gserviceaccount.com"
}

# Cloud Storage service agent (golden datasets + model cards buckets).
resource "google_kms_crypto_key_iam_member" "storage" {
  crypto_key_id = google_kms_crypto_key.model_quality_gate.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
}

# Vertex AI / Agent Runtime + Gen AI evaluation service agent.
resource "google_kms_crypto_key_iam_member" "aiplatform" {
  crypto_key_id = google_kms_crypto_key.model_quality_gate.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# Cloud Logging service agent (CMEK on the WORM bucket).
resource "google_kms_crypto_key_iam_member" "logging" {
  crypto_key_id = google_kms_crypto_key.model_quality_gate.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-logging.iam.gserviceaccount.com"
}
