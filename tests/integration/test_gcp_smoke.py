"""Live GCP smoke test : deselected in CI via ``-m 'not integration'``.

Requires real Google Cloud credentials and the ``[gcp]`` extra installed. It is skipped
automatically when ``GOOGLE_CLOUD_PROJECT`` is unset, so the default on-prem / test
profile (no Google Cloud SDK) never executes any of this. It constructs the managed
service adapters in the configured GCP region and does one trivial liveness call per adapter.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_CLOUD_PROJECT"),
        reason="set GOOGLE_CLOUD_PROJECT (and install the [gcp] extra) to run GCP smoke tests",
    ),
]


@pytest.fixture(scope="module")
def gcp_settings():
    from model_quality_gate.config import Settings

    settings = Settings.load("config/settings.yaml")
    return Settings(
        project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        region="us-central1",
        profile="gcp",
        kms_key=settings.kms_key,
        models=settings.models,
        eval=settings.eval,
        bigquery=settings.bigquery,
        storage=settings.storage,
        logging=settings.logging,
        agent_engine=settings.agent_engine,
        adapters=settings.adapters,
    )


@pytest.fixture(scope="module")
def container(gcp_settings):
    from model_quality_gate.config import Container

    return Container(gcp_settings)


def test_region_uses_configured_default(gcp_settings):
    assert gcp_settings.region == "us-central1"


def test_evaluation_adapter_constructs(container):
    # Constructing the Gen AI eval adapter must not require credentials (lazy client).
    assert container.evaluation is not None


def test_llm_judge_liveness(container):
    from model_quality_gate.domain.models import LlmMessage, LlmRequest

    request = LlmRequest(messages=(LlmMessage(role="user", content="ping"),))
    response = container.llm.generate(request)
    assert isinstance(response.text, str)


def test_tool_catalog_lists_governed_tools(container):
    tools = container.tool_catalog.list_tools()
    names = {t.name for t in tools}
    assert {"evaluate", "red_team", "promotion_gate", "version_prompt"} <= names


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", "-m", "integration"]))
