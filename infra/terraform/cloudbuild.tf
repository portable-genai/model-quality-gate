# cloudbuild.tf : The CI promotion gate (Cloud Build trigger).
#
# General Principle map:
#   P-08 (eval-gated promotion): A4 IS the gate. This Cloud Build trigger runs the
#         offline self-eval gate (eval/run_eval.py) plus the lint+test suite on every
#         push, and a release is not promotable unless the build is green. This is the
#         infra embodiment of rule R5 (every B/C agent must pass A4 before promotion).
#   P-06 (least privilege): the trigger runs as the dedicated cloudbuild service
#         account (iam.tf), not the default Cloud Build SA.
#
# The build config is inlined so the gate is self-contained; in a real repo it would
# point at a cloudbuild.yaml. Source is connected out of band (GitHub App / Cloud
# Source Repositories), so repo/owner are left as a documented placeholder.

resource "google_cloudbuild_trigger" "promotion_gate" {
  project     = var.project_id
  location    = var.region
  name        = "ai-quality-promotion-gate"
  description = "Runs ruff + pytest + the A4 self-eval gate; blocks promotion on failure (P-08)."

  service_account = google_service_account.cloudbuild.id

  # Connect to the repository out of band; this filter runs the gate on main pushes.
  github {
    owner = "REPLACE_WITH_GITHUB_OWNER"
    name  = "model-quality-gate"
    push {
      branch = "^main$"
    }
  }

  build {
    step {
      id         = "install"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      args       = ["-c", "pip install -e '.[dev]'"]
    }
    step {
      id         = "lint"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      args       = ["-c", "ruff check src tests && ruff format --check src tests"]
    }
    step {
      id         = "test"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      env        = ["AI_QUALITY_PROFILE=onprem"]
      args       = ["-c", "pytest -m 'not integration' -q"]
    }
    step {
      id         = "eval-gate"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      args       = ["-c", "python eval/run_eval.py"]
    }
    options {
      logging = "CLOUD_LOGGING_ONLY"
    }
  }

  depends_on = [google_project_service.required]
}
