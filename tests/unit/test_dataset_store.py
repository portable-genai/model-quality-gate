"""Unit tests for the golden-dataset ingest store (WP-C).

Covers the local DatasetStorePort adapter round trip, the store-preferred dataset
resolver, and the ingest/retrieve/score API flow (see
the shared evaluation contract, WP-C).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from model_quality_gate.adapters.local.dataset_store import LocalDatasetStoreAdapter
from model_quality_gate.api import deps
from model_quality_gate.api.app import app
from model_quality_gate.config import Container, LocalSettings, Settings
from model_quality_gate.pipelines.datasets import resolve_golden_dataset

_JSONL = (
    '{"id": "ex-1", "input": "What is the CDD source-of-wealth bar?", '
    '"expected_points": ["source of wealth"], "must_cite_ids": ["doc-1"]}\n'
    '{"id": "ex-2", "input": "another", "expected_points": [], "must_cite_ids": []}\n'
)


def _local_settings() -> Settings:
    base = Settings.load("config/settings.yaml")
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        local=LocalSettings(
            db_path=":memory:",
            audit_path=":memory:",
            registry_path=":memory:",
            model_cards_path=":memory:",
            metrics_path=":memory:",
            datasets_path=":memory:",
        ),
        adapters=base.adapters,
    )


# --------------------------------------------------------------------------- #
# Local adapter round trip
# --------------------------------------------------------------------------- #
def test_local_dataset_store_round_trip():
    store = LocalDatasetStoreAdapter(_local_settings())
    assert store.get("missing") is None
    assert store.list() == []

    store.put("doc1-golden", _JSONL.encode("utf-8"))
    assert store.get("doc1-golden") == _JSONL.encode("utf-8")
    assert store.list() == ["doc1-golden"]

    # put replaces (no duplicate id).
    store.put("doc1-golden", b'{"id": "ex-9", "input": "x"}\n')
    assert store.list() == ["doc1-golden"]
    assert b"ex-9" in (store.get("doc1-golden") or b"")


def test_resolve_prefers_store_over_bundled_disk():
    store = LocalDatasetStoreAdapter(_local_settings())
    store.put("ingested-set", _JSONL.encode("utf-8"))
    dataset = resolve_golden_dataset("ingested-set", store)
    assert dataset.n_examples == 2
    # A store miss falls back to the bundled loader (no crash, empty for an unknown id).
    assert resolve_golden_dataset("no-such-set", store).n_examples == 0


# --------------------------------------------------------------------------- #
# API flow
# --------------------------------------------------------------------------- #
_TARGET = {"model": "gemini-3.7-flash", "prompt_version": "v3", "dataset_id": "ingested-golden"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    container = Container(_local_settings())
    monkeypatch.setattr(deps, "get_container", lambda: container)
    yield TestClient(app, client=LOOPBACK_PEER)


def test_ingest_then_retrieve_and_score(client):
    ingest = client.post(
        "/v1/datasets",
        json={"dataset_id": "ingested-golden", "jsonl": _JSONL},
    )
    assert ingest.status_code == 201
    assert ingest.json() == {"dataset_id": "ingested-golden", "n_examples": 2}

    listed = client.get("/v1/datasets")
    assert listed.status_code == 200
    assert "ingested-golden" in listed.json()

    got = client.get("/v1/datasets/ingested-golden")
    assert got.status_code == 200
    assert got.json()["n_examples"] == 2

    # An evaluation against the ingested id resolves it from the store (not disk).
    scored = client.post(
        "/v1/evaluations",
        json={"target": _TARGET, "dataset_id": "ingested-golden"},
    )
    assert scored.status_code == 200
    assert scored.json()["n_examples"] == 2


def test_ingest_empty_dataset_is_422(client):
    resp = client.post(
        "/v1/datasets",
        json={"dataset_id": "empty", "jsonl": "# only a comment, no examples\n"},
    )
    assert resp.status_code == 422


def test_get_unknown_dataset_is_404(client):
    assert client.get("/v1/datasets/nope").status_code == 404


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
