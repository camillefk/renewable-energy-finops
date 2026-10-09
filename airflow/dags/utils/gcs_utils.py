"""
Upload helpers for the Bronze Layer (GCS) and structured logging.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

def build_bronze_blob_name(source: str, ds: str, city_id: str) -> str:
    """Builds the deterministic object path in the Bronze Layer.
    Example: "open-meteo/2026-09-25/rotterdam.json"
    """
    return f"{source}/{ds}/{city_id}.json"

def write_local_staging_file(local_dir: str, filename: str, payload: Dict[str, Any]) -> str:
    """Writes the payload to local disk (staging) before uploading.
 
    Kept outside the main task to facilitate unit testing without
    needing to mock GCS.
    """
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return local_path

def upload_file_to_gcs(bucket_name: str, blob_name: str, local_path: str) -> str:
    """Uploads a local file to the Bronze bucket (with overwrite).
    """
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)
    return f"gs://{bucket_name}/{blob_name}"

def log_event(logger_: logging.Logger, event: str, level: str = "info", **fields: Any) -> None:
    """Lightweight structured logging (without extra dependencies): one JSON per line.
    """
    record = {"event": event, **fields}
    getattr(logger_, level)(json.dumps(record, default=str))