"""DAG Airflow du pipeline raw -> staging -> curated."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task


@dag(
    dag_id="velibpulse_data_lake",
    description="Collecte periodique des disponibilites Velib'",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "Jacq VENGADESAN - BDML2",
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
    },
    tags=["datalake", "velib", "bdml2"],
)
def velib_data_lake():
    @task
    def initialize() -> None:
        from src.dependencies import get_service

        get_service().initialize()

    @task
    def ensure_reference() -> dict:
        from src.dependencies import get_service

        service = get_service()
        # L'upsert rend la tache idempotente; le CSV brut reste historise.
        return service.load_reference_file()

    @task
    def ingest_api_raw() -> str:
        from src.dependencies import get_service

        return get_service().ingest_api_to_raw()

    @task
    def transform_and_curate(raw_key: str) -> dict:
        from src.dependencies import get_service

        return get_service().process_status_key(raw_key, fast=True)

    ready = initialize()
    reference = ensure_reference()
    raw_key = ingest_api_raw()
    ready >> [reference, raw_key]
    [reference, raw_key] >> transform_and_curate(raw_key)


velib_data_lake()

