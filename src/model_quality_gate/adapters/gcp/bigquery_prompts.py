"""BigQuery prompt-registry adapter (PromptRegistryPort).

Backs the domain ``PromptRegistryPort`` with a BigQuery table of versioned, checksummed
prompts : the MRM change-control record for which exact prompt a target was gated under.
The ``google-cloud-bigquery`` import is lazy so the on-prem and test profiles import
without it.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import PromptVersion, utcnow


class BigQueryPromptRegistryAdapter:
    """Store and resolve versioned prompts in BigQuery."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _bq(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery  # lazy

            self._client = bigquery.Client(project=self._settings.project_id)
        return self._client

    @property
    def _table(self) -> str:
        bq = self._settings.bigquery
        return f"{self._settings.project_id}.{bq.dataset}.{bq.prompts_table}"

    # ------------------------------------------------------------------ #
    # PromptRegistryPort
    # ------------------------------------------------------------------ #
    def put(self, version: PromptVersion) -> None:
        client = self._bq()
        row = {
            "name": version.name,
            "version": version.version,
            "template": version.template,
            "checksum": version.checksum,
            "created_at": version.created_at.isoformat(),
        }
        errors = client.insert_rows_json(self._table, [row])
        if errors:  # pragma: no cover - surfaced only against a live table
            raise RuntimeError(f"BigQuery insert failed for prompt {version.name}: {errors}")

    def get(self, name: str, version: str) -> PromptVersion | None:
        client = self._bq()
        query = (
            f"SELECT name, version, template, checksum, created_at FROM `{self._table}` "
            "WHERE name = @name AND version = @version LIMIT 1"
        )
        from google.cloud import bigquery  # lazy

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("name", "STRING", name),
                bigquery.ScalarQueryParameter("version", "STRING", version),
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())
        return _row_to_prompt(rows[0]) if rows else None

    def list(self, name: str) -> list[PromptVersion]:
        client = self._bq()
        query = (
            f"SELECT name, version, template, checksum, created_at FROM `{self._table}` "
            "WHERE name = @name ORDER BY created_at DESC"
        )
        from google.cloud import bigquery  # lazy

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
        )
        return [_row_to_prompt(r) for r in client.query(query, job_config=job_config).result()]


def _row_to_prompt(row: Any) -> PromptVersion:
    return PromptVersion(
        name=str(row["name"]),
        version=str(row["version"]),
        template=str(row["template"]),
        checksum=str(row["checksum"] or ""),
        created_at=getattr(row["created_at"], "replace", lambda **_: utcnow())() or utcnow(),
    )
