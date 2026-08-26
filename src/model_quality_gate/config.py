"""Configuration and the adapter factory (dependency injection for the hexagon).

The factory reads ``config/settings.yaml`` (with ``${ENV_VAR}`` interpolation) and binds
each port to a concrete adapter by dotted path. Switching the whole system from the GCP
managed stack to an on-prem stack is a one-line change of ``profile`` : proof of the
ports-and-adapters / no-lock-in principle (P-02). Every adapter follows one construction
convention: ``Adapter(settings: Settings)``.

The profile is resolved in THREE states, not two: :func:`resolve_profile` is the only reader
of ``AI_QUALITY_PROFILE``, and it distinguishes unset (nobody chose), configured-empty (a boot
error), and ``local`` (someone chose the no-auth offline stack). The distinction is load bearing
because
``local`` is exactly the profile three relaxations are granted to (the S2S zero-secret
opening, the localhost CORS fallback, and the omission of HSTS), so reading an absent
variable as ``local`` turned a lost config map into a promotion gate that anyone could drive.
See :class:`ProfileChoice` for why the two derived strings point opposite ways.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from hex_service_kit.netdefaults import EnvSetting, read_env_setting

from .envread import setting_or_default

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")
DEFAULT_GCP_REGION = "us-central1"

#: The one environment variable that names the profile. Only :func:`resolve_profile` may read
#: it; ``tests/unit/test_profile_single_source.py`` fails the build if another module does.
_PROFILE_ENV = "AI_QUALITY_PROFILE"

#: Every profile that binds an adapter family. The comparison against it is EXACT and
#: case-sensitive, so ``Local`` is a typo that refuses rather than a silent choice.
RUNTIME_PROFILES = frozenset({"gcp", "local", "platform", "onprem"})

#: The profile string handed to every posture RELAXATION when no profile was ever named. It is
#: deliberately NOT a member of :data:`RUNTIME_PROFILES` and never reaches a :class:`Container`
#: binding: it exists so that "no choice was made" is a distinct input to the security layers
#: rather than being indistinguishable from a chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"


class ProfileError(RuntimeError):
    """Raised when a named profile is one nothing binds, including a capitalisation typo."""


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    Every posture decision downstream matches the profile string exactly, so ``Local``
    selects none of the relaxations but also none of the restrictions. Normalising the case
    here would turn a typo into a silent choice; refusing it turns the typo into a load
    failure, which is what an operator can actually see and fix.
    """
    if profile not in RUNTIME_PROFILES:
        expected = ", ".join(sorted(RUNTIME_PROFILES))
        raise ProfileError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {expected}")
    return profile


@dataclass(frozen=True)
class ProfileChoice:
    """The ONE resolution of the profile, and what each consumer must key off.

    The two derived profile strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" string would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent consent this is still ``local`` (the SDK-free
    #: stack), because the alternative would import cloud SDKs that are not installed.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (the env var, or a ``profile:`` value in the
    #: settings file, present and non-blank)?
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every *relaxation* keys off, where ``local`` is the PERMISSIVE case.

        Three relaxations are granted to ``local`` here: the S2S rule's zero-secret opening,
        the localhost CORS dev-origin fallback, and the omission of HSTS. An unconsented run
        must NOT look like ``local`` for any of them, so it gets :data:`UNCONSENTED_PROFILE`:
        no dev origins, HSTS on, and an unset shared secret is a refusal rather than consent.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay on loopback.
        """
        return self.profile if self.explicit else "local"

    @property
    def service_auth_configured(self) -> bool:
        """May S2S callers be authenticated at all, or is the decision unconfigured?"""
        return self.explicit


def resolve_profile(declared: str = "", environ: Mapping[str, str] | None = None) -> ProfileChoice:
    """Read the profile once: absent inherits confinement, empty refuses, and values validate.

    Three states, not two. ``AI_QUALITY_PROFILE`` wins when it has a value, configured-empty
    refuses instead of inheriting a default, and an absent variable permits a non-blank
    ``profile:`` in the settings file to be the deliberate choice. When neither source names
    one, nobody chose, which is not the same input as choosing ``local``.

    A value that IS present is validated here rather than at first port access, so a typo is
    a load failure naming the variable instead of a service that has already picked its
    posture from a string nothing binds.
    """
    if environ is None:
        setting = read_env_setting(_PROFILE_ENV)
    else:
        raw = environ.get(_PROFILE_ENV)
        setting = EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())
    if setting.is_configured_empty:
        raise ProfileError(
            f"{_PROFILE_ENV} is set but empty; unset it to inherit the confined offline stack, "
            f"or name one of {sorted(RUNTIME_PROFILES)}"
        )
    chosen = setting.value or (declared or "").strip()
    if chosen:
        _validate_profile(chosen)
        return ProfileChoice(profile=chosen, explicit=True)
    return ProfileChoice(profile="local", explicit=False)


class ResidencyError(RuntimeError):
    """Raised when the configured region is not on the residency allowlist (P-03).

    The same allowlist is enforced twice, deliberately: Terraform rejects an unapproved
    ``region`` at plan time (``variables.tf`` validation + the ``gcp.resourceLocations``
    Org Policy), and this check rejects it again at application load. A service that was
    pointed at an unapproved location by an environment variable after deploy must fail
    to start, not quietly process regulated evidence out of jurisdiction.
    """


def validate_residency(region: str, allowed_regions: list[str]) -> None:
    """Fail fast unless ``region`` is on the reviewed residency allowlist (P-03)."""
    if not allowed_regions:
        raise ResidencyError(
            "allowed_regions is empty: the residency allowlist must name at least one "
            "governance-approved region (P-03)."
        )
    if region not in allowed_regions:
        raise ResidencyError(
            f"region {region!r} is not on the residency allowlist "
            f"({', '.join(allowed_regions)}). Extend allowed_regions only after "
            "governance review, and in Terraform too (P-03)."
        )


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` tokens in strings recursively.

    ``${VAR:-default}`` is ``setting_or_default(name, default)`` one layer down, so it obeys the
    same rule and delegates to it: unset takes the written default, a value wins, and a variable
    an operator EMPTIED raises :class:`~hex_service_kit.netdefaults.ConfiguredEmptyError` rather
    than resolving to the empty string that is the permissive branch for a URL or an allowlist.
    """
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return setting_or_default(m.group(1), m.group(2) or "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


@dataclass(frozen=True)
class ModelSettings:
    #: The Vertex location the model client calls, NOT the compute region. Gemini 3
    #: serves the `us` and `eu` multi-regions only; `global` carries no residency
    #: guarantee. See models.location in config/settings.yaml.
    location: str = "us"
    reasoning: str = "gemini-3.7-flash"  # judge / reasoning model (thinking=high)
    triage: str = "gemini-3.1-flash-lite"  # routing / cheap triage
    hard_reasoning: str = "gemini-3.7-flash"  # Preview : feature-flagged off by default
    use_hard_reasoning: bool = False


@dataclass(frozen=True)
class EvalSettings:
    """Gen AI evaluation service settings (the A4 scoring backend)."""

    location: str = DEFAULT_GCP_REGION
    judge_model: str = "gemini-3.5-flash"
    experiment: str = "ai-quality-promotion-gate"


@dataclass(frozen=True)
class BigQuerySettings:
    """BigQuery datasets for eval metrics + drift dashboards."""

    dataset: str = "model_quality_gate"
    metrics_table: str = "eval_metrics"
    drift_table: str = "model_drift"
    prompts_table: str = "prompt_versions"


@dataclass(frozen=True)
class StorageSettings:
    """Cloud Storage buckets for golden datasets + model cards (CMEK)."""

    golden_bucket: str = "ai-quality-golden-datasets"
    model_cards_bucket: str = "ai-quality-model-cards"
    mrm_evidence_bucket: str = "ai-quality-mrm-evidence"


@dataclass(frozen=True)
class LoggingSettings:
    log_name: str = "ai-quality-audit"
    bucket: str = "ai-quality-worm"
    retention_days: int = 2557  # ~7 years


@dataclass(frozen=True)
class AgentEngineSettings:
    resource_name: str = ""  # reasoningEngine resource id, set after deploy
    display_name: str = "model-quality-gate"


@dataclass(frozen=True)
class LocalSettings:
    """Paths for the SDK-free ``local`` profile stores (SQLite FTS5 + SQLite stores).

    Empty strings select the per-package default under ``~/.model_quality_gate/``; tests pass
    ``:memory:`` for ephemeral, deterministic stores. No Google Cloud here.
    """

    db_path: str = ""  # SQLite FTS5 knowledge-base index; "" => ~/.model_quality_gate/local.db
    audit_path: str = ""  # append-only audit store;       "" => ~/.model_quality_gate/audit.db
    # The *prompt* registry store (LocalPromptRegistryAdapter). The agent registry
    # (LocalRegistryAdapter, AgentRegistryPort) is in-memory only and ignores this path.
    registry_path: str = ""  # prompt registry store;       "" => ~/.model_quality_gate/registry.db
    model_cards_path: str = ""  # model-card store;       "" => ~/.model_quality_gate/model_cards.db
    metrics_path: str = ""  # metrics / drift store;        "" => ~/.model_quality_gate/metrics.db
    datasets_path: str = ""  # golden-dataset store;        "" => ~/.model_quality_gate/datasets.db


@dataclass(frozen=True)
class Settings:
    project_id: str = "your-gcp-project"
    region: str = DEFAULT_GCP_REGION
    # local (default when AI_QUALITY_PROFILE unset) | gcp | platform | onprem
    profile: str = "local"
    kms_key: str = ""  # projects/.../cryptoKeys/... (regional)
    models: ModelSettings = field(default_factory=ModelSettings)
    eval: EvalSettings = field(default_factory=EvalSettings)
    bigquery: BigQuerySettings = field(default_factory=BigQuerySettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    agent_engine: AgentEngineSettings = field(default_factory=AgentEngineSettings)
    local: LocalSettings = field(default_factory=LocalSettings)
    # Bank-owned promotion policy (B4): the raw ``policy:`` mapping from settings.yaml.
    # The domain parses it (``PromotionPolicy.from_policy``); config only carries it, so
    # the domain never imports settings. Empty => the reference constants.
    policy: dict[str, Any] = field(default_factory=dict)
    # Residency-approved deployment regions (P-03 / D5). Mirrors the Terraform
    # ``allowed_regions`` variable; ``region`` is validated against it at load.
    allowed_regions: list[str] = field(default_factory=lambda: [DEFAULT_GCP_REGION])
    # port_name -> { profile -> "module.path:ClassName" }
    adapters: dict[str, dict[str, str]] = field(default_factory=dict)
    # Was the profile chosen DELIBERATELY, or merely inherited because nothing named one?
    # ``load`` sets this False when neither AI_QUALITY_PROFILE nor a ``profile:`` value in the
    # settings file is present. Direct construction is deliberate by definition (a caller named
    # the profile in code), so the default is True. Every posture RELAXATION reads
    # :attr:`exposure_profile` rather than :attr:`profile`, so an unconsented run does not
    # inherit the loopback-dev openings that ``local`` is granted.
    profile_explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every posture RELAXATION keys off (see :class:`ProfileChoice`)."""
        return ProfileChoice(self.profile, self.profile_explicit).exposure_profile

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off (see :class:`ProfileChoice`)."""
        return ProfileChoice(self.profile, self.profile_explicit).bind_profile

    def __post_init__(self) -> None:
        validate_residency(self.region, self.allowed_regions)

    @staticmethod
    def load(path: str | os.PathLike[str] | None = None) -> Settings:
        if path is None:
            setting = read_env_setting("AI_QUALITY_SETTINGS")
            if setting.is_configured_empty:
                raise ValueError(
                    "AI_QUALITY_SETTINGS is set but empty; unset it to use "
                    "config/settings.yaml, or provide a settings path"
                )
            path = setting.value or "config/settings.yaml"
        path = Path(path)
        raw = _interpolate(yaml.safe_load(path.read_text())) if path.exists() else {}
        raw = raw or {}
        nested = {
            "models": ModelSettings(**(raw.pop("models", {}) or {})),
            "eval": EvalSettings(**(raw.pop("eval", {}) or {})),
            "bigquery": BigQuerySettings(**(raw.pop("bigquery", {}) or {})),
            "storage": StorageSettings(**(raw.pop("storage", {}) or {})),
            "logging": LoggingSettings(**(raw.pop("logging", {}) or {})),
            "agent_engine": AgentEngineSettings(**(raw.pop("agent_engine", {}) or {})),
            "local": LocalSettings(**(raw.pop("local", {}) or {})),
        }
        # Three states, not two: neither the env var nor the settings file supplies a default,
        # so "nobody chose" stays distinguishable from "somebody chose local".
        choice = resolve_profile(str(raw.pop("profile", "") or ""))
        # The residency allowlist may also arrive as a comma-separated env value
        # (AI_QUALITY_ALLOWED_REGIONS) so a deployment can widen it without editing YAML.
        allowed = raw.get("allowed_regions")
        if isinstance(allowed, str):
            raw["allowed_regions"] = [r.strip() for r in allowed.split(",") if r.strip()]
        known = {f for f in Settings.__dataclass_fields__ if f not in nested}
        flat = {k: v for k, v in raw.items() if k in known}
        kwargs: dict[str, Any] = {
            "profile": choice.profile,
            "profile_explicit": choice.explicit,
            **flat,
            **nested,
        }
        return Settings(**kwargs)


def instantiate(dotted: str, settings: Settings) -> Any:
    """Import ``module.path:ClassName`` and construct it with ``settings``."""
    module_path, _, class_name = dotted.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(settings)


class Container:
    """Lazily-built registry of port -> adapter instances.

    Adapters are imported only on first access so that, e.g., a unit test using the
    on-prem profile never needs the Google Cloud SDKs installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port_name: str) -> Any:
        binding = self.settings.adapters.get(port_name, {})
        dotted = binding.get(self.settings.profile)
        if not dotted:
            raise KeyError(
                f"No adapter configured for port '{port_name}' "
                f"under profile '{self.settings.profile}'."
            )
        return instantiate(dotted, self.settings)

    # One cached_property per port keeps wiring declarative and type-greppable.
    @cached_property
    def evaluation(self) -> Any:
        return self._bind("evaluation")

    @cached_property
    def redteam(self) -> Any:
        return self._bind("redteam")

    @cached_property
    def dataset_store(self) -> Any:
        return self._bind("dataset_store")

    @cached_property
    def prompt_registry(self) -> Any:
        return self._bind("prompt_registry")

    @cached_property
    def model_card_store(self) -> Any:
        return self._bind("model_card_store")

    @cached_property
    def metrics_store(self) -> Any:
        return self._bind("metrics_store")

    @cached_property
    def knowledge_base(self) -> Any:
        return self._bind("knowledge_base")

    @cached_property
    def llm(self) -> Any:
        return self._bind("llm")

    @cached_property
    def audit(self) -> Any:
        return self._bind("audit")

    @cached_property
    def tracer(self) -> Any:
        return self._bind("tracer")

    @cached_property
    def registry(self) -> Any:
        return self._bind("registry")

    @cached_property
    def tool_catalog(self) -> Any:
        return self._bind("tool_catalog")

    @cached_property
    def identity(self) -> Any:
        return self._bind("identity")


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the SAME ``settings.adapters['identity']`` table :meth:`Container._bind` binds from,
    so a deployment that rebound the identity port (the documented on-premises path: swap the
    placeholder for the client's own IdP adapter, ``docs/onprem-migration.md``) is answered
    about the adapter it ACTUALLY runs, not about the one the profile name suggests.

    Constructing is deliberately avoided: an adapter's ``__init__`` reads settings and the
    environment, and a posture that can only be computed by constructing something disappears
    exactly when it matters most.
    """
    dotted = settings.adapters.get("identity", {}).get(settings.profile)
    if not dotted:
        raise KeyError(f"No identity adapter configured under profile {settings.profile!r}.")
    module_path, _, class_name = dotted.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {dotted!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See :mod:`model_quality_gate.ports.identity` for why neither the profile string on its own
    nor the presence of a service-to-service credential can answer it.

    Any failure to establish the answer resolves to
    :data:`~model_quality_gate.ports.identity.CLIENT_ASSERTED`. A guard that switches OFF because a
    lookup raised is a guard that fails open, and nothing is lost by failing closed here: the
    same failure surfaces loudly at the first request, when the container resolves the identical
    binding for real.
    """
    from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth

    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:  # noqa: BLE001 - a guard that fails open on a lookup error is no guard
        return CLIENT_ASSERTED
