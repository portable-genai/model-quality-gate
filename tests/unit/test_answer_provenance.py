"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the adapters NOTED as they
called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``, so
that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

Under ``local`` the deterministic scorer and red-team harness stand in for the managed ones, so
they note the offline stub, the same name ``generator_model`` reports. No adapter here attaches
an online search tool, so nothing notes a search in production; the route is still proved to
carry ``X-Search-Used`` the day one does, by binding a scorer that notes one on the real app.

The console calls this service directly (cross-origin when standalone), so the two headers are
also proved to be listed in ``Access-Control-Expose-Headers``: a browser hides every header
that list leaves out, and the pills would stay on the configured model forever.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from hex_service_kit import provenance
from tests.conftest import LOOPBACK_PEER
from tests.fixtures import sample_targets
from tests.fixtures.fake_genai import FakeGenaiClient, install_fake_genai

from model_quality_gate.adapters.gcp.gemini_llm import GeminiLLMAdapter
from model_quality_gate.adapters.gcp.gemini_redteam import GeminiRedTeamAdapter
from model_quality_gate.adapters.local.evaluation import LocalDeterministicEvalAdapter
from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.config import (
    STUB_GENERATOR_MODEL,
    Container,
    EvalSettings,
    LocalSettings,
    ModelSettings,
    Settings,
)
from model_quality_gate.domain.models import (
    EvalDataset,
    EvalTarget,
    LlmMessage,
    LlmRequest,
)
from model_quality_gate.pipelines.datasets import standard_redteam_cases

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"

_TARGET = {
    "model": "gemini-3.7-flash",
    "prompt_version": "v3",
    "dataset_id": "compliance-qa-golden",
    "system": "compliance-advisory",
}
_EVALUATE = {"target": _TARGET, "dataset_id": "compliance-qa-golden"}


def _local_container() -> Container:
    base = Settings.load("config/settings.yaml")
    return Container(
        Settings(
            project_id=base.project_id,
            region=base.region,
            profile="local",
            local=LocalSettings(
                db_path=":memory:",
                audit_path=":memory:",
                registry_path=":memory:",
                model_cards_path=":memory:",
                metrics_path=":memory:",
            ),
            adapters=base.adapters,
        )
    )


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Container:
    # `make portability` and the other CI targets run the suite with no profile exported.
    monkeypatch.setenv("AI_QUALITY_PROFILE", "local")
    built = _local_container()
    monkeypatch.setattr(deps, "get_container", lambda: built)
    return built


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(app, client=LOOPBACK_PEER)


@pytest.mark.parametrize(
    ("route", "body"),
    [("/v1/evaluations", _EVALUATE), ("/v1/redteam", {"target": _TARGET})],
)
def test_a_scored_request_names_the_model_generator_model_reports(
    client: TestClient, container: Container, route: str, body: dict
) -> None:
    """Under ``local`` the stub answered, and the pill names it exactly as /healthz did."""
    reply = client.post(route, json=body)
    assert reply.status_code == 200, reply.text
    assert reply.headers[ANSWERED_BY] == container.settings.generator_model
    assert reply.headers[ANSWERED_BY] == STUB_GENERATOR_MODEL == "deterministic-offline-stub"
    assert SEARCH_USED not in reply.headers


def test_a_route_that_called_no_model_names_none(client: TestClient) -> None:
    """Nothing noted, nothing sent: the pill never invents a model nobody called."""
    reply = client.get("/healthz")
    assert reply.status_code == 200, reply.text
    assert ANSWERED_BY not in reply.headers
    assert SEARCH_USED not in reply.headers


class _SearchingScorer(LocalDeterministicEvalAdapter):
    """The real offline scorer, plus what a scorer that searched would note as it called."""

    def score(self, target: EvalTarget, dataset: EvalDataset, metrics: list[str]) -> dict:
        scores = super().score(target, dataset, metrics)
        provenance.note_model("fake-searching-model")
        provenance.note_search()
        return scores


def test_a_call_that_searched_says_so_and_the_next_request_starts_clean(
    client: TestClient, container: Container
) -> None:
    container.__dict__["evaluation"] = _SearchingScorer(container.settings)
    reply = client.post("/v1/evaluations", json=_EVALUATE)
    assert reply.status_code == 200, reply.text
    assert reply.headers[SEARCH_USED] == "true"
    assert "fake-searching-model" in reply.headers[ANSWERED_BY]

    container.__dict__["evaluation"] = LocalDeterministicEvalAdapter(container.settings)
    after = client.post("/v1/evaluations", json=_EVALUATE)
    assert SEARCH_USED not in after.headers, "one request's search leaked into the next"
    assert after.headers[ANSWERED_BY] == STUB_GENERATOR_MODEL


def test_a_cross_origin_console_is_allowed_to_read_both_headers(client: TestClient) -> None:
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1, "the service has no CORS middleware for a console to call through"
    origins = cors[0].kwargs["allow_origins"]
    assert origins, "no allowed origin, so this would prove nothing"
    reply = client.post("/v1/evaluations", json=_EVALUATE, headers={"Origin": origins[0]})
    assert reply.status_code == 200, reply.text
    assert reply.headers["access-control-allow-origin"] == origins[0]
    exposed = {
        name.strip().lower()
        for value in reply.headers.get_list("access-control-expose-headers")
        for name in value.split(",")
    }
    assert {ANSWERED_BY, SEARCH_USED} <= exposed, exposed


def _gcp_settings() -> Settings:
    """``gcp`` settings whose model ids are all DISTINCT.

    Distinct so that agreement between what was called, what was noted and what
    ``generator_model`` reports cannot come from every setting being the same string.
    """
    base = Settings.load("config/settings.yaml")
    return dataclasses.replace(
        base,
        profile="gcp",
        models=ModelSettings(reasoning="the-reasoning-model", triage="the-triage-model"),
        eval=EvalSettings(judge_model="the-judge-model"),
    )


def test_the_gemini_judge_adapter_notes_the_model_it_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_genai(monkeypatch)
    adapter = GeminiLLMAdapter(_gcp_settings())
    fake = FakeGenaiClient()
    adapter._client = fake
    request = LlmRequest(messages=(LlmMessage(role="user", content="Judge this."),))
    with provenance.scope() as record:
        adapter.generate(request)
        adapter.generate(dataclasses.replace(request, model="an-explicit-model"))
        adapter.classify("text", ["pass", "fail"])
    called = [model for model, _ in fake.calls]
    assert called == ["the-reasoning-model", "an-explicit-model", "the-triage-model"]
    assert record.models == called, "a model answered that the pill would never name"
    assert record.search_used is False, "no call here attaches a search tool"


def test_the_gemini_red_team_notes_the_target_and_the_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_genai(monkeypatch)
    adapter = GeminiRedTeamAdapter(_gcp_settings())
    fake = FakeGenaiClient()
    adapter._client = fake
    target = sample_targets.SAMPLE_TARGET
    with provenance.scope() as record:
        adapter.run(target, standard_redteam_cases()[:1])
    called = [model for model, _ in fake.calls]
    assert called == [target.model, "the-judge-model"]
    assert record.models == called
    assert record.search_used is False


def test_generator_model_is_the_model_the_gemini_adapter_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    ``generator_model`` once named ``models.hard_reasoning`` when a hard-reasoning flag was
    set, while this adapter called ``request.model or models.reasoning`` and never read the
    flag. Measured here against the call itself.
    """
    install_fake_genai(monkeypatch)
    settings = _gcp_settings()
    adapter = GeminiLLMAdapter(settings)
    fake = FakeGenaiClient()
    adapter._client = fake
    adapter.generate(LlmRequest(messages=(LlmMessage(role="user", content="Judge this."),)))
    assert fake.calls[-1][0] == settings.generator_model == "the-reasoning-model"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    fields = {f.name for f in dataclasses.fields(ModelSettings)}
    assert "use_hard_reasoning" not in fields
    assert "hard_reasoning" not in fields, "a model nothing calls is a model a pill could name"
    repo = Path(__file__).resolve().parents[2]
    assert "hard_reasoning" not in (repo / "config" / "settings.yaml").read_text(encoding="utf-8")
    for source in sorted((repo / "src").rglob("*.py")):
        assert "hard_reasoning" not in source.read_text(encoding="utf-8"), source
