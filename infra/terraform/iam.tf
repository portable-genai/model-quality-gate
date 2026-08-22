# iam.tf : Least-privilege service accounts for the A4 workloads.
#
# General Principle map:
#   P-06 (least privilege / separation of duties): three distinct identities :
#         the app (serving the gate API), the agent runtime (the hosted ADK agent),
#         and Cloud Build (the CI promotion gate). Each gets only the roles it needs;
#         no shared "kitchen-sink" SA. This also supports maker-checker separation.
#   P-03 (residency): identities are project-scoped; data access is to in-region only.
#   P-09 (CMEK explicit): each SA that touches CMEK-encrypted data gets its own
#         cryptoKey use binding.

# ------------------------------- App (serving) ------------------------------ #
resource "google_service_account" "app" {
  account_id   = "ai-quality-app"
  display_name = "A4 AI Quality app (gate API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Serving path: run evals (aiplatform), write/read eval metrics + drift (BigQuery),
  # read/write model cards + golden datasets (GCS), write audit + traces, read secrets.
  app_roles = [
    "roles/aiplatform.user",     # Gen AI evaluation service + judge model
    "roles/bigquery.dataEditor", # record eval metrics + drift, read for dashboards
    "roles/bigquery.jobUser",    # run drift queries
    "roles/logging.logWriter",   # write audit events to the WORM sink
    "roles/cloudtrace.agent",    # OpenTelemetry spans (content OFF)
    "roles/secretmanager.secretAccessor",
    "roles/run.invoker",
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

resource "google_kms_crypto_key_iam_member" "app" {
  crypto_key_id = google_kms_crypto_key.model_quality_gate.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}

# --------------------------- Agent Runtime (ADK) ---------------------------- #
resource "google_service_account" "agent_runtime" {
  account_id   = "ai-quality-agent"
  display_name = "A4 Agent Runtime (reasoningEngine)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  agent_roles = [
    "roles/aiplatform.user",
    "roles/bigquery.dataEditor",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/secretmanager.secretAccessor",
  ]
}

resource "google_project_iam_member" "agent_runtime" {
  for_each = toset(local.agent_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.agent_runtime.email}"
}

locals {
  evidence_writers = {
    app           = google_service_account.app.email
    agent_runtime = google_service_account.agent_runtime.email
  }
}

resource "google_storage_bucket_iam_member" "golden_dataset_admin" {
  for_each = local.evidence_writers
  bucket   = google_storage_bucket.golden_datasets.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${each.value}"
}

resource "google_storage_bucket_iam_member" "model_card_admin" {
  for_each = local.evidence_writers
  bucket   = google_storage_bucket.model_cards.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${each.value}"
}

resource "google_storage_bucket_iam_member" "mrm_evidence_creator" {
  for_each = local.evidence_writers
  bucket   = google_storage_bucket.mrm_evidence.name
  role     = "roles/storage.objectCreator"
  member   = "serviceAccount:${each.value}"
}

resource "google_storage_bucket_iam_member" "mrm_evidence_viewer" {
  for_each = local.evidence_writers
  bucket   = google_storage_bucket.mrm_evidence.name
  role     = "roles/storage.objectViewer"
  member   = "serviceAccount:${each.value}"
}

# ------------------------------- Cloud Build -------------------------------- #
resource "google_service_account" "cloudbuild" {
  account_id   = "ai-quality-cloudbuild"
  display_name = "A4 CI promotion-gate Cloud Build runner"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # The CI gate only needs to run tests + the eval gate and write its own logs.
  cloudbuild_roles = [
    "roles/logging.logWriter",
    "roles/aiplatform.user", # optional --use-gcp path against the eval service
  ]
}

resource "google_project_iam_member" "cloudbuild" {
  for_each = toset(local.cloudbuild_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.cloudbuild.email}"
}
