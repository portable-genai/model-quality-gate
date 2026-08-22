"""Contract tests: the ``onprem`` and ``local`` adapters are structural parity of the ports.

For every port the catalog declares, this iterates the adapter map and, for both the
``onprem`` and ``local`` profiles, imports + constructs the bound class (which must build
cleanly with **no Google Cloud SDK** installed), then asserts:

  1. the constructed instance satisfies its runtime_checkable Protocol (isinstance), and
  2. every method/property the Protocol declares actually exists on the instance.

It additionally proves the two profiles' distinct contracts:

* ``onprem`` is the fail-fast Google Distributed Cloud migration target: every method
  raises ``NotImplementedError`` (proven on a representative port), and
* ``local`` is a WORKING offline stack: the same ports construct and score / retrieve
  in-process.

This is the proof of the ports-and-adapters / no-lock-in promise (P-02): the on-prem
migration target and the offline local stack implement the exact same interface as the
managed GCP stack.
"""

from __future__ import annotations

from typing import Protocol, get_type_hints

import pytest

from model_quality_gate import config, ports
from model_quality_gate.config import Container, LocalSettings, Settings, instantiate

CONFIG_PATH = "config/settings.yaml"

# Every port name in settings.adapters mapped to its Protocol.
PORT_PROTOCOLS: dict[str, type] = {
    "evaluation": ports.EvaluationPort,
    "redteam": ports.RedTeamPort,
    "dataset_store": ports.DatasetStorePort,
    "prompt_registry": ports.PromptRegistryPort,
    "model_card_store": ports.ModelCardStorePort,
    "metrics_store": ports.MetricsStorePort,
    "knowledge_base": ports.KnowledgeBaseClientPort,
    "llm": ports.LLMPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
    "identity": ports.IdentityPort,
}

# Profiles whose adapters must construct + satisfy the Protocols with no GCP SDK.
SDK_FREE_PROFILES = ("onprem", "local")


def _settings(profile: str) -> Settings:
    base = Settings.load(CONFIG_PATH)
    # Point the local stores at in-memory SQLite so the contract test stays ephemeral.
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile=profile,
        kms_key=base.kms_key,
        models=base.models,
        eval=base.eval,
        bigquery=base.bigquery,
        storage=base.storage,
        logging=base.logging,
        agent_engine=base.agent_engine,
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
        ),
        adapters=base.adapters,
    )


def _protocol_members(protocol: type) -> set[str]:
    """The attribute names a Protocol declares (methods + properties), no dunders."""
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    if not members:
        # Fallback for older typing internals: union of annotations + callables.
        members |= set(get_type_hints(protocol).keys())
        for name in dir(protocol):
            if name.startswith("_"):
                continue
            members.add(name)
    return {m for m in members if not m.startswith("_")}


def test_port_protocols_matches_settings_adapters():
    """The hand-maintained PORT_PROTOCOLS map must EQUAL the ports bound in settings.

    ``test_every_port_has_onprem_and_local_bindings`` only walks PORT_PROTOCOLS, so it
    catches a *removed* binding but not an *added* one: a fork that binds a brand-new port
    in ``config/settings.yaml`` and forgets its PORT_PROTOCOLS entry gets ZERO parity /
    constructor / onprem-binding enforcement with a green CI (silent drift). This
    set-equality guard fails loudly on drift in BOTH directions: an unregistered
    ``settings.adapters`` key, or a PORT_PROTOCOLS entry with no binding.
    """
    settings = Settings.load(CONFIG_PATH)
    bound = set(settings.adapters)
    declared = set(PORT_PROTOCOLS)
    missing_from_map = bound - declared
    missing_from_settings = declared - bound
    assert not missing_from_map, (
        f"ports bound in settings.adapters but absent from PORT_PROTOCOLS "
        f"(so untested): {sorted(missing_from_map)}. Add them to the parity map."
    )
    assert not missing_from_settings, (
        f"ports in PORT_PROTOCOLS with no settings.adapters binding: "
        f"{sorted(missing_from_settings)}."
    )


def test_every_port_has_an_explicit_binding_for_every_profile():
    settings = Settings.load(CONFIG_PATH)
    for port_name in PORT_PROTOCOLS:
        binding = settings.adapters.get(port_name, {})
        missing = set(config.RUNTIME_PROFILES) - set(binding)
        assert not missing, f"port '{port_name}' has no explicit bindings for {sorted(missing)}"


def test_profile_matrix_is_explicit_and_bounded():
    """A profile addition or accidental fallback must be a reviewed contract change."""
    settings = Settings.load(CONFIG_PATH)
    for port_name, binding in settings.adapters.items():
        expected = set(config.RUNTIME_PROFILES)
        assert set(binding) == expected, (
            f"port '{port_name}' profiles changed: "
            f"expected {sorted(expected)}, got {sorted(binding)}"
        )


def test_unknown_profile_fails_closed_instead_of_falling_back_to_gcp():
    settings = _settings("unconfigured-provider")
    with pytest.raises(KeyError, match="No adapter configured.*unconfigured-provider"):
        _ = Container(settings).evaluation


def test_platform_constructs_all_ports_from_explicit_bindings():
    settings = _settings("platform")
    container = Container(settings)
    for port_name in PORT_PROTOCOLS:
        adapter = container._bind(port_name)  # noqa: SLF001 - profile wiring contract
        selected = settings.adapters[port_name]["platform"]
        module, _, class_name = selected.partition(":")
        assert type(adapter).__module__ == module
        assert type(adapter).__name__ == class_name


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_satisfies_protocol(profile: str, port_name: str):
    settings = _settings(profile)
    protocol = PORT_PROTOCOLS[port_name]
    dotted = settings.adapters[port_name][profile]

    # Import + construct with only Settings (the adapter convention), no GCP SDK.
    adapter = instantiate(dotted, settings)

    # 1. Structural conformance via runtime_checkable Protocol.
    assert isinstance(adapter, protocol), (
        f"{dotted} does not structurally satisfy {protocol.__name__}"
    )

    # 2. Every declared Protocol member exists. Check on the *class* (via the MRO), not the
    #    instance: a placeholder property getter may raise, so ``hasattr`` would wrongly
    #    report it missing. Looking the name up on the type tests for declaration without
    #    invoking the getter.
    members = _protocol_members(protocol)
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in members:
        assert member in declared, (
            f"{dotted} is missing port method/attr '{member}' of {protocol.__name__}"
        )


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_constructs_with_single_settings_arg(profile: str, port_name: str):
    """The build contract: every adapter is ``Adapter(settings: Settings)``."""
    settings = _settings(profile)
    dotted = settings.adapters[port_name][profile]
    module_path, _, class_name = dotted.partition(":")
    import importlib

    cls = getattr(importlib.import_module(module_path), class_name)
    # Must accept exactly one positional Settings argument and build cleanly.
    instance = cls(settings)
    assert instance is not None


def test_onprem_evaluation_fails_fast():
    """The on-prem stubs are fail-fast: a representative port raises NotImplementedError."""
    settings = _settings("onprem")
    adapter = instantiate(settings.adapters["evaluation"]["onprem"], settings)
    from model_quality_gate.domain.models import EvalDataset, EvalTarget

    with pytest.raises(NotImplementedError):
        adapter.score(
            EvalTarget(model="m", prompt_version="v1", dataset_id="d"),
            EvalDataset(id="d"),
            ["groundedness"],
        )


def test_local_knowledge_base_returns_real_citations():
    """The local stack is WORKING: the KB returns real, page-cited passages offline."""
    settings = _settings("local")
    adapter = instantiate(settings.adapters["knowledge_base"]["local"], settings)

    citations = adapter.retrieve("cloud outsourcing due diligence", top_k=5)
    assert citations, "local FTS5 knowledge base returned nothing for the seeded corpus"
    assert any(c.page is not None for c in citations), "page-level citation required"


def test_local_evaluation_scores_real_metrics():
    """The local evaluation scorer returns real per-metric scores in [0,1] offline."""
    settings = _settings("local")
    adapter = instantiate(settings.adapters["evaluation"]["local"], settings)
    from tests.fixtures import sample_targets

    scores = adapter.score(
        sample_targets.SAMPLE_TARGET,
        sample_targets.SAMPLE_DATASET,
        ["groundedness", "citation_accuracy", "safety"],
    )
    assert set(scores) == {"groundedness", "citation_accuracy", "safety"}
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_all_protocols_are_runtime_checkable():
    for protocol in PORT_PROTOCOLS.values():
        assert issubclass(protocol, Protocol)  # type: ignore[arg-type]
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{protocol.__name__} must be @runtime_checkable"
        )


def test_shared_types_are_the_commons_objects_not_local_copies():
    """The shared ports and value types must BE the commons objects, not look-alikes.

    ``isinstance`` against a ``runtime_checkable`` Protocol passes for a hand-copied
    look-alike, so every structural test above stays green while a repo quietly keeps its
    own redeclaration and drifts from the commons. ``is`` does not: it fails the moment
    anyone reintroduces a local ``class TokenUsage`` / ``class IdentityPort`` /
    ``class Principal``. That drift is the defect this repo was carrying, and object
    identity is the only assertion that can see it.
    """
    from hex_service_kit import identity as commons_identity
    from hex_service_kit import observability as commons_observability

    from model_quality_gate.domain import identity as domain_identity
    from model_quality_gate.domain import models

    assert ports.ObservabilityTracerPort is commons_observability.ObservabilityTracerPort
    assert ports.TokenUsage is commons_observability.TokenUsage
    assert models.TokenUsage is commons_observability.TokenUsage
    assert ports.IdentityPort is commons_identity.IdentityPort
    assert domain_identity.Principal is commons_identity.Principal
    assert domain_identity.RequestContext is commons_identity.RequestContext
    assert domain_identity.IdentityError is commons_identity.IdentityError
    assert domain_identity.ANONYMOUS is commons_identity.ANONYMOUS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
