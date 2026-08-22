# posture_alerts.tf : alerting on residency / perimeter posture violations.
#
# General Principle map:
#   P-03 (residency): a dry-run VPC-SC perimeter and an Org Policy denial are only useful
#         if somebody is told. These log-based metrics turn the audit-log entries for
#         (a) VPC Service Controls violations (dry-run and enforced alike) and
#         (b) location-policy denials into counters, and alert on any occurrence.
#   P-08 (auditability): the alert is the evidence that the dry-run period was actually
#         watched rather than waited out.
#
# Notification channels are an adopter input: with none configured the alert policies still
# exist and fire, they just have no destination, so leaving var.alert_notification_channels
# empty is a deliberate (visible) choice and not a silent hole.

resource "google_logging_metric" "vpc_sc_violations" {
  name        = "model_quality_gate_vpc_sc_violations"
  description = "VPC Service Controls violations affecting this project (dry-run or enforced)."
  project     = var.project_id

  filter = join(" AND ", [
    "log_id(\"cloudaudit.googleapis.com/policy\")",
    "protoPayload.metadata.@type=\"type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata\"",
  ])

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_logging_metric" "resource_location_denials" {
  name        = "model_quality_gate_resource_location_denials"
  description = "Org Policy denials, including gcp.resourceLocations residency denials."
  project     = var.project_id

  filter = join(" AND ", [
    "log_id(\"cloudaudit.googleapis.com/activity\")",
    "protoPayload.status.message:\"constraints/gcp.resourceLocations\"",
  ])

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "posture_violation" {
  project      = var.project_id
  display_name = "A4 residency / perimeter posture violation"
  combiner     = "OR"

  documentation {
    content = join("\n", [
      "A residency or perimeter control was hit.",
      "VPC-SC: while vpc_sc_enforce = false the perimeter is a DRY RUN, so this is a call",
      "that WOULD have been blocked. Investigate before enforcing.",
      "resourceLocations: a resource creation was denied outside var.allowed_regions.",
    ])
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "VPC Service Controls violation"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.vpc_sc_violations.name}\" AND resource.type=\"global\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }

  conditions {
    display_name = "Resource-location policy denial"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.resource_location_denials.name}\" AND resource.type=\"global\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }

  notification_channels = var.alert_notification_channels

  depends_on = [google_project_service.required]
}
