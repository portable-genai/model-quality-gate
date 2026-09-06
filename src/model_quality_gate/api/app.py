"""FastAPI application for the A4 AI Quality & Model-Risk Platform.

Exposes the A4 promotion-gate contract that sibling repos consume (every B/C agent must
pass A4 before promotion, rule R5):

* ``POST /v1/evaluations`` -> EvalReport
* ``POST /v1/redteam``      -> RedTeamReport
* ``POST /v1/gate``         -> GateDecision
* ``GET  /v1/gate``         -> {passed}  (the cheap promotion check)
* ``GET  /v1/drift/{model}`` -> DriftEscalation (the online-quality read; an ``alert``
  requires a re-gate, and this route never runs one)
* ``GET/POST /v1/prompts/{name}/versions``
* ``GET  /v1/model-cards/{model}/{version}``
* ``GET  /healthz`` and ``GET /.well-known/agent-card.json``

Design constraints:

* **Import-safe.** Building the :class:`~model_quality_gate.config.Container` is deferred to
  request time via the ``deps`` factories, so importing this module never touches Google
  Cloud. The on-prem/test profile imports it with no GCP SDK installed.
* **Region selected at deploy time**, defaulting to ``asia-southeast1`` (SPEC §2).

Run locally with ``python -m model_quality_gate.api.app`` (uvicorn on :8084).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from hex_service_kit import cors_allowlist, read_env_setting, resolve_bind_host
from hex_service_kit.capabilities import (
    AssuranceLevel,
    Capability,
    CapabilityManifest,
    CapabilityMode,
)
from hex_service_kit.web import add_loopback_exposure_guard, add_security_headers

from ..config import end_user_auth_kind
from ..domain.errors import EmptyDatasetError, UnknownMetricError
from ..domain.models import PromptVersion
from ..domain.serialization import mrm_evidence_jsonable
from ..domain.services import (
    DriftMonitorService,
    EvaluationService,
    ModelCardService,
    PromotionGateService,
    PromptVersioningService,
    RedTeamService,
)
from ..pipelines.datasets import (
    parse_golden_jsonl,
    resolve_golden_dataset,
    standard_redteam_cases,
)
from ..ports.identity import VERIFIED
from . import deps
from .schemas import (
    AgentCardModel,
    CapabilityManifestModel,
    DatasetIngestRequest,
    DatasetSummaryModel,
    DriftEscalationModel,
    EvalReportModel,
    EvaluateRequest,
    GateDecisionModel,
    GateRequest,
    GateStatusResponse,
    HealthResponse,
    ModelCardModel,
    PromptVersionModel,
    PromptVersionRequest,
    RedTeamReportModel,
    RedTeamRequest,
)
from .security import CurrentPrincipal, ServiceCaller

_DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Embedding-surface controls. In secure/embedded mode the service is served same-origin via
# the parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone dev
# case, AI_QUALITY_CORS_ORIGINS is an explicit per-tenant allowlist (never "*").
# AI_QUALITY_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins
# permitted to iframe the UI.
_FRAME_ANCESTORS_ENV = "AI_QUALITY_FRAME_ANCESTORS"
_CORS_ORIGINS_ENV = "AI_QUALITY_CORS_ORIGINS"


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a SANDBOXED iframe presents the origin
#: ``null``, so allowing it hands framing and credentialed cross-origin rights to any page able
#: to open one. ``'*'`` is what a quoted Terraform variable or a YAML string renders, and ``*.*``
#: is a host pattern matching every name with a dot in it. The same set is refused on the
#: document half, in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: Sequence[str], variable: str) -> None:
    """A ``*`` in an origin policy is the policy switched off, so it never boots.

    Both allowlists resolved their unset and emptied states carefully and then passed the
    value on verbatim, so ``*`` reached ``CORSMiddleware(allow_origins=["*"])`` and
    ``Content-Security-Policy: frame-ancestors *``. With ``allow_credentials=True`` that lets
    any page on the internet read this gate's responses cross-origin, and any page frame the
    console. The prohibition was written down in a comment beside each variable, and in the
    shared kit's docstring for CORS, and enforced by neither.

    Raised where the value is RESOLVED, which is module import, so an operator whose config
    template rendered a wildcard finds out when the service refuses to start rather than when
    a browser somewhere exercises it.

    A test of ``"*" in origins`` is a membership test over the SEQUENCE, so it
    sees an entry that IS an asterisk and not one that CONTAINS one: ``https://*.client.example``
    goes straight through, and CSP honours that host-source form, so every subdomain could frame
    the console including one obtained by takeover or serving user content. Nothing downstream
    inspected these values either, so the other spellings reached a response header verbatim.
    Both halves of the rule are needed: a real origin never contains the character and is never
    one of :data:`_WILDCARD_TOKENS`, so this refuses nothing a deployment could correctly hold.
    """
    offending = [
        origin for origin in origins if "*" in origin or origin.strip() in _WILDCARD_TOKENS
    ]
    if offending:
        raise ValueError(
            f"{variable} contains {offending}: the origin policy must never contain a "
            "wildcard. Name the exact parent or caller origins instead, or unset the variable "
            "to keep the shipped default."
        )


def _frame_ancestors(raw: str | None) -> str:
    """Three-state read of ``AI_QUALITY_FRAME_ANCESTORS``; an emptied value REFUSES to boot.

    Unset is not a member of the valid value set, so this resolves three states rather than
    two. Unset keeps the shipped ``'self'``. Set to a value naming no origin used to reach
    ``add_security_headers`` as ``""``, which emitted the header
    ``Content-Security-Policy: frame-ancestors`` with an EMPTY directive: browsers discard
    that as a parse error, and the ``== "'self'"`` branch that adds ``X-Frame-Options`` was
    skipped as well, so the clickjacking control vanished from both channels at once with
    nothing in the response to show it.

    An empty string is not a usable value for this read, so it refuses at boot rather than
    serving a posture nobody chose. A total lockdown is expressible and stays available:
    set the variable to ``'none'``. Refusing is loud and immediate (uvicorn imports this
    module at start-up), which is what an operator whose config template rendered an empty
    value needs to see.
    """
    if raw is None:
        return "'self'"
    ancestors = " ".join(raw.split())
    if not ancestors:
        raise ValueError(
            f"{_FRAME_ANCESTORS_ENV} is set to an empty value: it names no parent origin, and "
            "an empty CSP frame-ancestors directive is a parse error that browsers discard, "
            "taking the clickjacking restriction with it. Unset it to keep the shipped "
            "'self' default, or set it to 'none' to refuse all framing."
        )
    _refuse_wildcard(ancestors.split(), _FRAME_ANCESTORS_ENV)
    return ancestors


_FRAME_ANCESTORS = _frame_ancestors(read_env_setting(_FRAME_ANCESTORS_ENV).raw)


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*"; the localhost dev fallback applies ONLY under the
    local profile (shared hex-service-kit rule).

    Keyed off ``exposure_profile``, because this is a RELAXATION: a run that never named a
    profile must not inherit the dev origins, which would otherwise let arbitrary local
    processes on a user's machine call a promotion gate cross-origin with credentials.

    The local refusal runs FIRST, on the raw configured value, rather than on what the kit
    hands back. ``cors_allowlist`` now refuses the same wildcards itself, so on the old order
    the kit raised its own ``InsecureCorsError`` before this module's rule was ever reached and
    the policy quietly changed owner. Refusing on the way in keeps :func:`_refuse_wildcard` the
    one authority over both allowlists: a single exception type and a single message naming the
    variable an operator must fix, whether the value came from CORS or from frame-ancestors.
    The kit's check stays as an unreachable backstop, which is what a backstop should be.
    """
    configured = read_env_setting(_CORS_ORIGINS_ENV).value
    _refuse_wildcard(
        [origin.strip() for origin in configured.split(",") if origin.strip()], _CORS_ORIGINS_ENV
    )
    return cors_allowlist(
        deps.get_settings().exposure_profile,
        origins_env=_CORS_ORIGINS_ENV,
        dev_origins=tuple(_DEV_ORIGINS),
    )


app = FastAPI(
    title="A4 AI Quality & Model-Risk Platform",
    version="0.1.0",
    description=(
        "The production-promotion eval / red-team gate and model-risk (MRM) evidence "
        "system for APAC banking, on the Gemini Enterprise Agent Platform. Returns a "
        "PASS/FAIL GateDecision and the EvalReport / RedTeamReport behind it."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


# Security-header baseline (practice C6), from the shared commons rather than a local
# copy: CSP frame-ancestors (+ X-Frame-Options when it is 'self'), X-Content-Type-Options
# nosniff, Referrer-Policy, and HSTS on every non-local profile (where TLS terminates in
# front of the service). The local profile is plain-HTTP loopback, so HSTS is omitted
# there: pinning a laptop origin to https would break the offline demo. Omitting HSTS is a
# RELAXATION, so it reads exposure_profile: a run that never named a profile gets HSTS.
add_security_headers(
    app,
    frame_ancestors=_FRAME_ANCESTORS,
    profile=deps.get_settings().exposure_profile,
)


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme at all; and it is
#      the one case where a settings file that bound a verifying adapter must NOT buy the
#      relaxation, because unset is not consent, whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it VERIFIES the end user.
#      Seeded personas arrive on the X-Dev-Persona header the caller wrote and default to a
#      persona when the header is absent entirely; the on-premises placeholder resolves nobody.
#      Neither authenticates anyone, so neither may switch this off. The adapter is read from
#      the BINDING, so an adopter who wires their own IdP verifier under `onprem` lifts the
#      bound without touching this expression.
#
# Note what is NOT in this expression: AI_QUALITY_S2S_TOKEN. A service credential is evidence
# about a calling SERVICE and says nothing about the end-user routes, so setting one must not,
# and cannot, disable their bound. S2S routes are bounded by their own dependency.
_END_USER_AUTHENTICATED = (
    deps.get_settings().profile_explicit and end_user_auth_kind(deps.get_settings()) == VERIFIED
)

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as `local`;
# this widens the same rule to every posture that cannot authenticate an end user, so the
# start-up bound in `main()` and the request-time guard agree instead of one binding every
# interface while the other refuses every peer that reaches it.
_BIND_PROFILE = deps.get_settings().bind_profile if _END_USER_AUTHENTICATED else "local"

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. Bound to the APP
# OBJECT, not to `main()`: the Dockerfile CMD is
# `exec uvicorn model_quality_gate.api.app:app --host 0.0.0.0 --port ${PORT}`, which never reaches
# `main()`, so a guard living only there is dead in every shipped process. Executed before this
# existed: a peer at 203.0.113.7 read the whole seeded-persona roster off `/v1/personas` and the
# golden-dataset list off `/v1/datasets`.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env="AI_QUALITY_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=deps.get_settings().exposure_profile,
)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
@app.post(
    "/v1/evaluations",
    response_model=EvalReportModel,
    tags=["quality"],
    dependencies=[ServiceCaller],
)
def evaluations(
    request: EvaluateRequest,
    principal: CurrentPrincipal,
    service: Annotated[EvaluationService, Depends(deps.get_evaluation_service)],
    dataset_store: Annotated[object, Depends(deps.get_dataset_store)],
) -> EvalReportModel:
    """Evaluate a target against a golden dataset and return the EvalReport."""
    dataset = resolve_golden_dataset(request.dataset_id, dataset_store)
    try:
        thresholds = deps.get_promotion_policy().thresholds_for(request.bundle, request.metrics)
        report = service.evaluate(
            request.target.to_domain(), dataset, principal.actor, thresholds=thresholds
        )
    except (EmptyDatasetError, UnknownMetricError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return EvalReportModel.from_domain(report)


# --------------------------------------------------------------------------- #
# Golden-dataset ingest (WP-C)
# --------------------------------------------------------------------------- #
@app.post(
    "/v1/datasets",
    response_model=DatasetSummaryModel,
    status_code=status.HTTP_201_CREATED,
    tags=["quality"],
    dependencies=[ServiceCaller],
)
def ingest_dataset(
    request: DatasetIngestRequest,
    principal: CurrentPrincipal,
    dataset_store: Annotated[object, Depends(deps.get_dataset_store)],
) -> DatasetSummaryModel:
    """Publish a golden dataset (JSONL) so targets can be scored against it.

    Refuses an empty golden set: a dataset with no examples would drive a vacuous gate.
    Requires a verified principal (an unauthenticated caller is 401 upstream); with S2S
    auth this narrows to service callers.
    """
    parsed = parse_golden_jsonl(request.dataset_id, request.jsonl)
    if parsed.n_examples == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="golden dataset has no examples",
        )
    dataset_store.put(request.dataset_id, request.jsonl.encode("utf-8"))  # type: ignore[attr-defined]
    return DatasetSummaryModel(dataset_id=request.dataset_id, n_examples=parsed.n_examples)


@app.get("/v1/datasets", response_model=list[str], tags=["quality"], dependencies=[ServiceCaller])
def list_datasets(
    principal: CurrentPrincipal,
    dataset_store: Annotated[object, Depends(deps.get_dataset_store)],
) -> list[str]:
    """List the ids of every ingested golden dataset."""
    return list(dataset_store.list())  # type: ignore[attr-defined]


@app.get(
    "/v1/datasets/{dataset_id}",
    response_model=DatasetSummaryModel,
    tags=["quality"],
    dependencies=[ServiceCaller],
)
def get_dataset(
    dataset_id: str,
    principal: CurrentPrincipal,
    dataset_store: Annotated[object, Depends(deps.get_dataset_store)],
) -> DatasetSummaryModel:
    """Return a stored golden dataset's id + example count, or 404 if absent."""
    blob = dataset_store.get(dataset_id)  # type: ignore[attr-defined]
    if blob is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
    parsed = parse_golden_jsonl(dataset_id, blob.decode("utf-8"))
    return DatasetSummaryModel(dataset_id=dataset_id, n_examples=parsed.n_examples)


# --------------------------------------------------------------------------- #
# Red-team
# --------------------------------------------------------------------------- #
@app.post(
    "/v1/redteam",
    response_model=RedTeamReportModel,
    tags=["quality"],
    dependencies=[ServiceCaller],
)
def redteam(
    request: RedTeamRequest,
    principal: CurrentPrincipal,
    service: Annotated[RedTeamService, Depends(deps.get_redteam_service)],
) -> RedTeamReportModel:
    """Run the adversarial red-team harness against a target."""
    cases = standard_redteam_cases(request.categories)
    report = service.run(request.target.to_domain(), cases, principal.actor)
    return RedTeamReportModel.from_domain(report)


# --------------------------------------------------------------------------- #
# Promotion gate (the A4 contract other repos consume)
# --------------------------------------------------------------------------- #
@app.post(
    "/v1/gate",
    response_model=GateDecisionModel,
    tags=["gate"],
    dependencies=[ServiceCaller],
)
def gate(
    request: GateRequest,
    principal: CurrentPrincipal,
    service: Annotated[PromotionGateService, Depends(deps.get_gate_service)],
    dataset_store: Annotated[object, Depends(deps.get_dataset_store)],
) -> GateDecisionModel:
    """Run the full PASS/FAIL promotion gate and return the GateDecision with evidence.

    This POST is the authoritative promotion verdict: an unknown/empty dataset is a 422
    here, never a silent ``{"passed": false}`` (that trap lives only on the cheap GET).
    """
    dataset = resolve_golden_dataset(request.dataset_id, dataset_store)
    cases = standard_redteam_cases()
    try:
        thresholds = deps.get_promotion_policy().thresholds_for(request.bundle, request.metrics)
        decision = service.gate(
            request.target.to_domain(), dataset, cases, principal.actor, thresholds
        )
    except (EmptyDatasetError, UnknownMetricError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return GateDecisionModel.from_domain(decision)


@app.get(
    "/v1/gate",
    response_model=GateStatusResponse,
    tags=["gate"],
    dependencies=[ServiceCaller],
)
def gate_status(
    model: str,
    prompt_version: str,
    dataset: str,
    principal: CurrentPrincipal,
    service: Annotated[PromotionGateService, Depends(deps.get_gate_service)],
    dataset_store: Annotated[object, Depends(deps.get_dataset_store)],
) -> GateStatusResponse:
    """The cheap promotion check: does ``model@prompt_version`` pass against ``dataset``?

    This is the endpoint sibling promotion pipelines poll (rule R5). It runs the gate and
    returns only the boolean verdict. An unknown/empty dataset is a 404 (WP-D): a poller
    must be able to tell "does not exist" from a genuine FAIL, which the old silent
    ``{"passed": false}`` hid. Prefer ``POST /v1/gate`` for the authoritative verdict.
    """
    from ..domain.models import EvalTarget

    target = EvalTarget(model=model, prompt_version=prompt_version, dataset_id=dataset)
    golden = resolve_golden_dataset(dataset, dataset_store)
    try:
        decision = service.gate(target, golden, standard_redteam_cases(), principal.actor)
    except EmptyDatasetError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"dataset {dataset!r} not found or empty",
        ) from exc
    return GateStatusResponse(passed=decision.passed)


@app.get(
    "/v1/mrm-evidence/{run_id}",
    response_model=dict[str, Any],
    tags=["mrm"],
    dependencies=[ServiceCaller],
)
def get_mrm_evidence(
    run_id: str,
    store: Annotated[object, Depends(deps.get_model_card_store)],
) -> dict[str, Any]:
    """Resolve one immutable promotion artifact by its evaluation run ID.

    Served through ``mrm_evidence_jsonable`` so the two sub-report verdicts (computed
    properties, invisible to the bare field walk) reach an independent verifier.
    """
    evidence = store.get_evidence(run_id)  # type: ignore[attr-defined]
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MRM evidence not found")
    return mrm_evidence_jsonable(evidence)


# --------------------------------------------------------------------------- #
# Online quality drift (the read an operator or a model-risk dashboard makes)
# --------------------------------------------------------------------------- #
@app.get(
    "/v1/drift/{model}",
    response_model=DriftEscalationModel,
    tags=["mrm"],
    dependencies=[ServiceCaller],
)
def model_drift(
    model: str,
    principal: CurrentPrincipal,
    service: Annotated[DriftMonitorService, Depends(deps.get_drift_service)],
) -> DriftEscalationModel:
    """Report ``model``'s recorded quality drift and what it now owes a human.

    This is the read that makes ``MetricsStorePort.drift`` reachable: before it, the
    signals were computed for a dashboard the reader had to build, so an ``alert`` reached
    nobody. An ``alert`` here sets ``requires_re_gate``, which is a REQUIREMENT and not an
    action: this route holds no gate service and promotes nothing.

    A model with nothing recorded against it is **not** a 404 and **not** a calm reading.
    It answers 200 with ``status: "unmeasured"`` and ``requires_re_gate: true``, because a
    poller must be able to tell "no evidence" from "evidence that looks fine", and because
    an absent measurement is never a pass.
    """
    return DriftEscalationModel.from_domain(service.assess(model, principal.actor))


# --------------------------------------------------------------------------- #
# Prompt versioning
# --------------------------------------------------------------------------- #
@app.post(
    "/v1/prompts/{name}/versions",
    response_model=PromptVersionModel,
    status_code=status.HTTP_201_CREATED,
    tags=["mrm"],
    dependencies=[ServiceCaller],
)
def register_prompt_version(
    name: str,
    request: PromptVersionRequest,
    principal: CurrentPrincipal,
    service: Annotated[PromptVersioningService, Depends(deps.get_prompt_service)],
) -> PromptVersionModel:
    """Register a versioned, checksummed prompt (MRM change-control evidence)."""
    version = PromptVersion(name=name, version=request.version, template=request.template)
    stored = service.register(version, principal.actor)
    return PromptVersionModel.from_domain(stored)


@app.get(
    "/v1/prompts/{name}/versions",
    response_model=list[PromptVersionModel],
    tags=["mrm"],
    dependencies=[ServiceCaller],
)
def list_prompt_versions(
    name: str,
    principal: CurrentPrincipal,
    service: Annotated[PromptVersioningService, Depends(deps.get_prompt_service)],
) -> list[PromptVersionModel]:
    """List every registered version of a named prompt."""
    return [PromptVersionModel.from_domain(v) for v in service.list(name)]


# --------------------------------------------------------------------------- #
# Model cards
# --------------------------------------------------------------------------- #
@app.get(
    "/v1/model-cards/{model}/{version}",
    response_model=ModelCardModel,
    tags=["mrm"],
    dependencies=[ServiceCaller],
)
def get_model_card(
    model: str,
    version: str,
    principal: CurrentPrincipal,
    service: Annotated[ModelCardService, Depends(deps.get_model_card_service)],
) -> ModelCardModel:
    """Resolve a model card (MRM evidence) by model + version."""
    card = service.get(model, version)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model card not found")
    return ModelCardModel.from_domain(card)


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #
@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    """Liveness probe plus honest assurance posture."""
    manifest = _capability_manifest()
    settings = deps.get_settings()
    return HealthResponse(
        status="ok",
        profile=manifest.profile,
        runtime=settings.runtime,
        generator_model=settings.generator_model,
        region=manifest.region,
        production_ready=manifest.production_ready,
        demo_only=manifest.demo_only,
    )


@app.get("/v1/capabilities", response_model=CapabilityManifestModel, tags=["ops"])
def capabilities() -> CapabilityManifestModel:
    """Report selected adapters and assurance without probing or inventing cloud success."""
    return _capability_manifest()


def _capability_manifest() -> CapabilityManifestModel:
    settings = deps.get_settings()
    demo_only = settings.profile == "local"
    managed = settings.profile in {"gcp", "platform"}
    mode = (
        CapabilityMode.LOCAL
        if demo_only
        else (CapabilityMode.MANAGED if managed else CapabilityMode.DISABLED)
    )
    definitions = (
        (
            "evaluation",
            "Gemini Enterprise Agent Evaluation",
            bool(settings.adapters.get("evaluation", {}).get(settings.profile)),
            "AI_QUALITY_EVALUATION_ATTESTATION_REF",
        ),
        (
            "model-risk-evidence",
            "regional evidence stores",
            bool(settings.adapters.get("metrics_store", {}).get(settings.profile))
            and bool(settings.adapters.get("model_card_store", {}).get(settings.profile)),
            "AI_QUALITY_EVIDENCE_ATTESTATION_REF",
        ),
        (
            "immutable-audit",
            "agent-observability / Cloud Logging WORM",
            bool(read_env_setting("OBSERVABILITY_URL").value),
            "AI_QUALITY_AUDIT_ATTESTATION_REF",
        ),
        (
            "trace-correlation",
            "agent-observability / OpenTelemetry",
            bool(read_env_setting("OTEL_EXPORTER_OTLP_ENDPOINT").value),
            "AI_QUALITY_TRACE_ATTESTATION_REF",
        ),
    )
    items: list[Capability] = []
    for name, provider, configured, attestation_env in definitions:
        available = demo_only or (managed and configured)
        attestation_ref = read_env_setting(attestation_env).value
        assurance = (
            AssuranceLevel.DEMO_ONLY
            if demo_only
            else (
                AssuranceLevel.ATTESTED
                if available and attestation_ref
                else AssuranceLevel.NOT_ATTESTED
            )
        )
        reason = (
            "deterministic laptop implementation; not promotion evidence"
            if demo_only
            else (
                f"deployment evidence: {attestation_ref}"
                if attestation_ref
                else (
                    "configured but no independent deployment attestation is bound"
                    if available
                    else "required managed endpoint or adapter is not configured"
                )
            )
        )
        items.append(
            Capability(
                name=name,
                available=available,
                mode=mode,
                assurance=assurance if available else AssuranceLevel.UNAVAILABLE,
                provider=provider,
                reason=reason,
                required_for_production=True,
            )
        )
    # production_ready is NOT recomputed here. The kit manifest derives it from the same
    # capabilities this function just built, so the served flag and the rule that decides it
    # can no longer disagree; that rule used to be written out again, right here.
    return CapabilityManifestModel.from_manifest(
        CapabilityManifest(
            service="model-quality-gate",
            profile=settings.profile,
            region=settings.region,
            capabilities=tuple(items),
            demo_only=demo_only,
        )
    )


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity
    (and thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure
    profiles resolve identity from the IAP assertion, so this returns an empty list.
    """
    identity = deps.get_container().identity
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


@app.get("/.well-known/agent-card.json", response_model=AgentCardModel, tags=["governance"])
def agent_card() -> AgentCardModel:
    """Publish this service's A2A AgentCard for discovery (A3 Registry / interop)."""
    from ..agent.agent_card import build_agent_card

    settings = deps.get_settings()
    card = build_agent_card(settings)
    return AgentCardModel.from_domain(card)


def main() -> None:
    """Run the API locally with uvicorn; the SECOND layer of the exposure bound, not the only one.

    This refuses to BIND a non-loopback interface, which is the earlier and clearer failure, but
    it runs only when the process is started through this function. The shipped entry point is
    not: the Dockerfile CMD hands ``model_quality_gate.api.app:app`` straight to uvicorn with
    ``--host 0.0.0.0``. The bound that always applies is the ``add_loopback_exposure_guard``
    middleware registered on the app object above; do not delete it believing this covers it.
    """

    import uvicorn

    # Fail-closed bind (shared hex-service-kit rule): the no-auth local
    # profile binds loopback unless AI_QUALITY_ALLOW_INSECURE_DEMO=1; secure profiles keep
    # 0.0.0.0 (container-local; ingress is fronted by the platform). This is the RESTRICTION
    # half of the profile decision, so it reads _BIND_PROFILE: a run that never named a
    # profile, and any posture that cannot authenticate an end user, looks like local here and
    # stays on loopback, the opposite direction from the relaxations above.
    uvicorn.run(
        "model_quality_gate.api.app:app",
        host=resolve_bind_host(
            _BIND_PROFILE,
            host_env="AI_QUALITY_API_HOST",
            insecure_demo_env="AI_QUALITY_ALLOW_INSECURE_DEMO",
        ),
        port=int(os.environ.get("PORT", "8084")),
        reload=os.environ.get("AI_QUALITY_API_RELOAD") == "1",
    )


if __name__ == "__main__":
    main()
