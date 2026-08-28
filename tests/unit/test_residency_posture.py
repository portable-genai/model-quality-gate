"""Residency and sovereignty posture (practice D5), enforced offline.

Two halves, both checkable with no cloud project in the loop:

* **Runtime.** ``Settings`` refuses to load with a region that is not on the reviewed
  residency allowlist, so a service repointed by an environment variable after deploy
  fails to start rather than quietly processing regulated evidence out of jurisdiction.
* **Posture-as-code.** The Terraform in ``infra/terraform`` carries the controls the
  practice names: the ``gcp.resourceLocations`` Org Policy built from the SAME allowlist,
  a dry-run-first VPC-SC perimeter, per-service CMEK bindings, and alerting on residency /
  perimeter violations. These are static assertions over the ``.tf`` sources: they prove
  the configuration is written, NOT that a live project enforces it. Live enforcement
  evidence needs a named deployment and is tracked separately in docs/practices-audit.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from model_quality_gate.config import (
    DEFAULT_GCP_REGION,
    ResidencyError,
    Settings,
    validate_residency,
)

TF_DIR = Path(__file__).resolve().parents[2] / "infra" / "terraform"


def _tf(name: str) -> str:
    return (TF_DIR / name).read_text()


# --------------------------------------------------------------------------- #
# Runtime: the allowlist is enforced at application load
# --------------------------------------------------------------------------- #
def test_region_outside_the_allowlist_is_rejected_at_load(tmp_path: Path) -> None:
    """A region not on the allowlist must fail the service closed, not warn."""
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "project_id: p\nregion: europe-west4\nallowed_regions: [asia-southeast1]\nprofile: local\n"
    )
    with pytest.raises(ResidencyError) as exc:
        Settings.load(settings_file)
    assert "europe-west4" in str(exc.value)
    assert "asia-southeast1" in str(exc.value)


def test_allowlisted_region_loads(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "project_id: p\nregion: europe-west4\n"
        "allowed_regions: [asia-southeast1, europe-west4]\nprofile: local\n"
    )
    assert Settings.load(settings_file).region == "europe-west4"


def test_comma_separated_allowlist_from_env_is_parsed(tmp_path: Path) -> None:
    """The env override form (AI_QUALITY_ALLOWED_REGIONS=a,b) interpolates to a string."""
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "project_id: p\nregion: asia-southeast1\n"
        "allowed_regions: asia-southeast1, asia-southeast1\nprofile: local\n"
    )
    settings = Settings.load(settings_file)
    assert settings.allowed_regions == ["asia-southeast1", "asia-southeast1"]


def test_empty_allowlist_is_rejected() -> None:
    """An empty allowlist is a configuration hole, not 'anything goes'."""
    with pytest.raises(ResidencyError):
        validate_residency(DEFAULT_GCP_REGION, [])


def test_shipped_settings_region_is_on_its_own_allowlist() -> None:
    """The committed config/settings.yaml must itself be residency-consistent."""
    settings = Settings.load("config/settings.yaml")
    assert settings.region in settings.allowed_regions


# --------------------------------------------------------------------------- #
# Posture-as-code: the Terraform carries the D5 controls
# --------------------------------------------------------------------------- #
def test_org_policy_pins_resource_locations_to_the_same_allowlist() -> None:
    """Residency must be an org-level constraint, not just this module's convention."""
    org_policy = _tf("org_policy.tf")
    assert "gcp.resourceLocations" in org_policy
    # Built from var.allowed_regions: one list, enforced at plan, org and runtime.
    assert "var.allowed_regions" in org_policy
    assert "allowed_values = local.allowed_location_groups" in org_policy


def test_org_policy_disables_service_account_key_creation() -> None:
    assert "iam.disableServiceAccountKeyCreation" in _tf("org_policy.tf")


def test_vpc_sc_perimeter_is_dry_run_first() -> None:
    """The perimeter must default to audit-only so enforcement never locks out a live project."""
    vpc_sc = _tf("vpc_sc.tf")
    assert "use_explicit_dry_run_spec = !var.vpc_sc_enforce" in vpc_sc
    # The enforced `status` block exists only when an operator opts in.
    assert 'dynamic "status"' in vpc_sc
    assert 'dynamic "spec"' in vpc_sc

    variables = _tf("variables.tf")
    assert 'variable "vpc_sc_enforce"' in variables
    # Dry run is the default: the enforce flag ships false.
    enforce_block = variables[variables.index('variable "vpc_sc_enforce"') :]
    enforce_block = enforce_block[: enforce_block.index("\n}")]
    assert "default     = false" in enforce_block


def test_region_variable_is_validated_against_the_allowlist() -> None:
    variables = _tf("variables.tf")
    assert "contains(var.allowed_regions, var.region)" in variables


def test_cmek_is_bound_per_service_because_it_does_not_cascade() -> None:
    """P-09: every service that stores evidence names the key explicitly."""
    kms = _tf("kms.tf")
    assert "google_kms_crypto_key" in kms
    bigquery = _tf("bigquery.tf")
    storage = _tf("cloud_storage.tf")
    assert "kms_key_name" in bigquery or "default_kms_key_name" in bigquery
    assert "kms_key_name" in storage or "default_kms_key_name" in storage


def test_posture_violations_raise_an_alert() -> None:
    """A dry-run perimeter is only useful if somebody is told about the violations."""
    alerts = _tf("posture_alerts.tf")
    assert "VpcServiceControlAuditMetadata" in alerts
    assert "constraints/gcp.resourceLocations" in alerts
    assert "google_monitoring_alert_policy" in alerts


def test_ci_validates_terraform_offline() -> None:
    """fmt + validate run on every PR with no cloud credentials."""
    ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yaml").read_text()
    assert "terraform fmt -check -recursive" in ci
    assert "terraform init -backend=false -input=false" in ci
    assert "terraform validate" in ci
