"""FastAPI dependency wiring for the A4 AI Quality & Model-Risk service.

This module builds a single, process-wide :class:`~model_quality_gate.config.Container` (the
ports-and-adapters registry) and assembles the orchestration services from the
Container's port instances. The Container is created lazily on first access so importing
this module : and therefore the FastAPI app : never touches Google Cloud: a unit test or
the on-prem profile can import the API with no GCP SDK installed.

Each ``get_*`` factory is a FastAPI ``Depends`` provider. Services take *explicit port
instances* in their constructors (SPEC §5), so the wiring here is the single place that
knows which ports each service needs.
"""

from __future__ import annotations

from functools import lru_cache

from ..config import Container, Settings, build_container
from ..domain.policy import PromotionPolicy
from ..domain.services import (
    EvaluationService,
    ModelCardService,
    PromotionGateService,
    PromptVersioningService,
    RedTeamService,
)


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide Container, building it on first use."""
    return build_container(Settings.load())


def get_settings() -> Settings:
    """Convenience accessor for the active settings (region, profile, models...)."""
    return get_container().settings


@lru_cache(maxsize=1)
def get_promotion_policy() -> PromotionPolicy:
    """Return the deployment's promotion policy, parsed from settings ``policy:`` (B4).

    Cached: the policy is fixed for the process lifetime, and parsing it once means an
    invalid override fails the first request loudly rather than intermittently.
    """
    return PromotionPolicy.from_policy(get_settings().policy)


def get_dataset_store() -> object:
    """Return the active DatasetStorePort adapter (golden-set ingest/resolve)."""
    return get_container().dataset_store


def get_model_card_store() -> object:
    """Return the evidence store for immutable run-artifact resolution."""
    return get_container().model_card_store


# --------------------------------------------------------------------------- #
# Service factories : assemble each service from the Container's ports.
# Constructor argument order mirrors SPEC §5 exactly.
# --------------------------------------------------------------------------- #


def build_evaluation_service(container: Container) -> EvaluationService:
    """Build evaluation orchestration with both immutable and analytical evidence stores."""
    return EvaluationService(
        evaluation=container.evaluation,
        knowledge_base=container.knowledge_base,
        llm=container.llm,
        tracer=container.tracer,
        audit=container.audit,
        metrics_store=container.metrics_store,
    )


def build_redteam_service(container: Container) -> RedTeamService:
    """RedTeamService(redteam, tracer, audit)."""
    return RedTeamService(
        redteam=container.redteam,
        tracer=container.tracer,
        audit=container.audit,
    )


def build_gate_service(container: Container) -> PromotionGateService:
    """PromotionGateService(evaluation_service, redteam_service, model_card_store, ...).

    The maker-checker borderline band is bank-owned policy (B4), so the review policy is
    built from the configured ``policy:`` section rather than the code constant.
    """
    return PromotionGateService(
        evaluation_service=build_evaluation_service(container),
        redteam_service=build_redteam_service(container),
        model_card_store=container.model_card_store,
        tracer=container.tracer,
        audit=container.audit,
        review_policy=PromotionPolicy.from_policy(container.settings.policy).review_policy(),
    )


def build_prompt_service(container: Container) -> PromptVersioningService:
    """PromptVersioningService(prompt_registry, tracer, audit)."""
    return PromptVersioningService(
        prompt_registry=container.prompt_registry,
        tracer=container.tracer,
        audit=container.audit,
    )


def build_model_card_service(container: Container) -> ModelCardService:
    """ModelCardService(model_card_store, tracer, audit)."""
    return ModelCardService(
        model_card_store=container.model_card_store,
        tracer=container.tracer,
        audit=container.audit,
    )


# --------------------------------------------------------------------------- #
# FastAPI Depends providers (cached, process-wide Container).
# --------------------------------------------------------------------------- #


def get_evaluation_service() -> EvaluationService:
    return build_evaluation_service(get_container())


def get_redteam_service() -> RedTeamService:
    return build_redteam_service(get_container())


def get_gate_service() -> PromotionGateService:
    return build_gate_service(get_container())


def get_prompt_service() -> PromptVersioningService:
    return build_prompt_service(get_container())


def get_model_card_service() -> ModelCardService:
    return build_model_card_service(get_container())


def create_app():  # -> FastAPI
    """App factory used by uvicorn ``--factory`` and the CLI ``serve`` command."""
    from .app import app

    return app
