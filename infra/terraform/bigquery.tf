# bigquery.tf : Eval-metrics + model-drift datasets (the A4 quality store).
#
# General Principle map:
#   P-03 (residency): the dataset location is the configured approved region.
#   P-07 (model-risk evidence): every eval run is recorded here so a model-risk
#         committee can trace a target's metric history and detect drift over time.
#   P-09 (CMEK explicit): the dataset's default_encryption_configuration uses the
#         regional key (CMEK does not cascade : BigQuery needs its own key binding).
#
# Tables (eval_metrics, model_drift, prompt_versions) match config/settings.yaml
# bigquery.* names and are created with explicit schemas so the adapters can insert
# rows without an ad-hoc CREATE.

resource "google_bigquery_dataset" "model_quality_gate" {
  dataset_id  = "model_quality_gate" # matches settings.yaml bigquery.dataset
  project     = var.project_id
  location    = var.region
  description = "A4 AI quality: eval metrics, model drift, and prompt-version change control."

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.model_quality_gate.id # CMEK explicit (P-09)
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.bigquery,
  ]
}

resource "google_bigquery_table" "eval_metrics" {
  dataset_id          = google_bigquery_dataset.model_quality_gate.dataset_id
  table_id            = "eval_metrics" # matches settings.yaml bigquery.metrics_table
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "model", type = "STRING", mode = "REQUIRED" },
    { name = "prompt_version", type = "STRING", mode = "REQUIRED" },
    { name = "dataset_id", type = "STRING", mode = "REQUIRED" },
    # Added as NULLABLE so an existing protected table can evolve in place. The
    # application requires these values for every newly written eval-run/v1 row.
    { name = "run_id", type = "STRING", mode = "NULLABLE" },
    { name = "dataset_version", type = "STRING", mode = "NULLABLE" },
    { name = "dataset_digest", type = "STRING", mode = "NULLABLE" },
    { name = "evaluator", type = "STRING", mode = "NULLABLE" },
    { name = "attested", type = "BOOL", mode = "NULLABLE" },
    { name = "schema_version", type = "STRING", mode = "NULLABLE" },
    { name = "artifact_refs", type = "STRING", mode = "REPEATED" },
    { name = "example_evidence", type = "JSON", mode = "NULLABLE" },
    { name = "metric", type = "STRING", mode = "REQUIRED" },
    { name = "score", type = "FLOAT", mode = "REQUIRED" },
    { name = "threshold", type = "FLOAT", mode = "REQUIRED" },
    { name = "passed", type = "BOOL", mode = "REQUIRED" },
    { name = "n_examples", type = "INTEGER", mode = "NULLABLE" },
    { name = "recorded_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "model_drift" {
  dataset_id          = google_bigquery_dataset.model_quality_gate.dataset_id
  table_id            = "model_drift" # matches settings.yaml bigquery.drift_table
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "model", type = "STRING", mode = "REQUIRED" },
    { name = "metric", type = "STRING", mode = "REQUIRED" },
    { name = "baseline", type = "FLOAT", mode = "REQUIRED" },
    { name = "current", type = "FLOAT", mode = "REQUIRED" },
    { name = "drift", type = "FLOAT", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "observed_at", type = "TIMESTAMP", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "prompt_versions" {
  dataset_id          = google_bigquery_dataset.model_quality_gate.dataset_id
  table_id            = "prompt_versions" # matches settings.yaml bigquery.prompts_table
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "name", type = "STRING", mode = "REQUIRED" },
    { name = "version", type = "STRING", mode = "REQUIRED" },
    { name = "template", type = "STRING", mode = "REQUIRED" },
    { name = "checksum", type = "STRING", mode = "REQUIRED" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}
