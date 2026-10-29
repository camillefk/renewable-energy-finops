"""Thin BigQuery helpers (authentication via Application Default Credentials)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)


def get_client(project: Optional[str] = None) -> bigquery.Client:
    """ADC/WIF-authenticated client. `project=None` falls back to the ADC project."""
    return bigquery.Client(project=project)


def _to_schema_fields(schema_def: List[Tuple[str, str]]) -> List[bigquery.SchemaField]:
    return [bigquery.SchemaField(name, bq_type, mode="REQUIRED") for name, bq_type in schema_def]


def ensure_silver_table(
    client: bigquery.Client,
    dataset: str,
    table: str,
    schema_def: List[Tuple[str, str]],
) -> str:
    """Create the Silver table if missing: DAY-partitioned on observed_at, clustered by city_id.

    Returns the fully-qualified table id. If the table already exists (e.g. created
    by Terraform) it is left untouched, so its schema must match `schema_def`.
    """
    table_id = f"{client.project}.{dataset}.{table}"
    bq_table = bigquery.Table(table_id, schema=_to_schema_fields(schema_def))
    bq_table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="observed_at"
    )
    bq_table.clustering_fields = ["city_id"]
    client.create_table(bq_table, exists_ok=True)
    return table_id


def load_rows_to_staging(
    client: bigquery.Client,
    dataset: str,
    table_name: str,
    rows: List[Dict[str, Any]],
    schema_def: List[Tuple[str, str]],
    ttl_days: int,
) -> str:
    """Batch load job (free, unlike streaming inserts) into a self-expiring staging table.

    WRITE_TRUNCATE makes the step idempotent: a retry replaces the previous attempt.
    """
    staging_id = f"{client.project}.{dataset}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        schema=_to_schema_fields(schema_def),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, staging_id, job_config=job_config).result()

    staging = client.get_table(staging_id)
    staging.expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    client.update_table(staging, ["expires"])
    return staging_id


def run_merge(client: bigquery.Client, sql: str) -> int:
    """Run the MERGE and return the number of affected rows (inserted + updated)."""
    job = client.query(sql)
    job.result()
    return int(job.num_dml_affected_rows or 0)