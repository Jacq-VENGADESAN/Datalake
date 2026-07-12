from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.config import Settings
from src.models import IngestResponse, StationStatusInput
from src.storage.database import Database
from src.storage.object_store import ObjectStore
from src.transformations import (
    curate_naive,
    curate_vectorized,
    inputs_to_staging,
    parse_gbfs_payload,
    parse_reference_csv,
)

logger = logging.getLogger(__name__)


class DataLakeService:
    def __init__(self, settings: Settings, store: ObjectStore, database: Database) -> None:
        self.settings = settings
        self.store = store
        self.database = database

    @staticmethod
    def _timestamp_key() -> str:
        return datetime.now(UTC).strftime("%Y/%m/%d/%H%M%S_%f")

    def initialize(self) -> None:
        self.store.ensure_bucket()
        self.database.initialize()

    def ingest_reference_to_raw(self, path: Path | None = None) -> str:
        source_path = path or self.settings.reference_csv_path
        content = source_path.read_bytes()
        key = f"reference/{self._timestamp_key()}_stations.csv"
        return self.store.put_bytes(key, content, "text/csv; charset=utf-8")

    def process_reference_key(self, key: str) -> int:
        records = parse_reference_csv(self.store.get_bytes(key))
        return self.database.upsert_references(records)

    def load_reference_file(self, path: Path | None = None) -> dict[str, Any]:
        key = self.ingest_reference_to_raw(path)
        return {"raw_key": key, "staged": self.process_reference_key(key)}

    def ingest_api_to_raw(self) -> str:
        with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
            response = client.get(self.settings.velib_status_url)
            response.raise_for_status()
            # Stockage des octets recus, sans reserialisation: la zone raw reste fidele.
            content = response.content
            json.loads(content)  # validation minimale avant archivage
        key = f"api/velib_status/{self._timestamp_key()}_status.json"
        return self.store.put_bytes(key, content, "application/json")

    def process_status_key(self, key: str, fast: bool = True) -> dict[str, Any]:
        payload = json.loads(self.store.get_bytes(key))
        snapshots = parse_gbfs_payload(payload)
        references = self.database.reference_map()
        curated = (
            curate_vectorized(snapshots, references)
            if fast
            else curate_naive(snapshots, references)
        )
        staged_count = self.database.insert_snapshots_bulk(snapshots)
        curated_count = self.database.insert_curated_bulk(curated)
        return {
            "raw_key": key,
            "received": len(snapshots),
            "staged": staged_count,
            "curated": curated_count,
        }

    def run_api_pipeline(self) -> dict[str, Any]:
        return self.process_status_key(self.ingest_api_to_raw(), fast=True)

    def ingest_gateway(
        self, items: list[StationStatusInput], *, fast: bool
    ) -> IngestResponse:
        started = time.perf_counter()
        mode = "fast" if fast else "standard"
        raw_payload = {"data": [item.model_dump(mode="json") for item in items], "mode": mode}
        raw_key = f"gateway/{mode}/{self._timestamp_key()}_batch.json"
        self.store.put_json(raw_key, raw_payload)

        snapshots = inputs_to_staging(items)
        references = self.database.reference_map()
        if fast:
            curated = curate_vectorized(snapshots, references)
            staged_count = self.database.insert_snapshots_bulk(snapshots)
            curated_count = self.database.insert_curated_bulk(curated)
        else:
            curated = curate_naive(snapshots, references)
            staged_count = self.database.insert_snapshots_one_by_one(snapshots)
            curated_count = self.database.insert_curated_one_by_one(curated)
        duration_ms = (time.perf_counter() - started) * 1000
        return IngestResponse(
            mode=mode,
            received=len(items),
            staged=staged_count,
            curated=curated_count,
            raw_key=raw_key,
            duration_ms=round(duration_ms, 3),
        )

    def health(self) -> dict[str, Any]:
        services: dict[str, dict[str, str]] = {}
        overall = "healthy"
        for name, check in (("minio", self.store.ping), ("postgresql", self.database.ping)):
            try:
                check()
                services[name] = {"status": "up"}
            except Exception as exc:  # endpoint de supervision: retourne l'erreur au lieu de tomber
                logger.warning("Health check %s en echec: %s", name, exc)
                services[name] = {"status": "down", "error": str(exc)}
                overall = "degraded"
        return {
            "status": overall,
            "api": "up",
            "timestamp": datetime.now(UTC).isoformat(),
            "services": services,
        }

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat()}
        for name, operation in (("raw", self.store.stats), ("database", self.database.stats)):
            try:
                result[name] = operation()
            except Exception as exc:
                logger.warning("Stats %s indisponibles: %s", name, exc)
                result[name] = {"error": str(exc)}
        return result

