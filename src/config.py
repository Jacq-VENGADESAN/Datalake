from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration centralisee, surchargeable par variables d'environnement."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    project_name: str = "VelibPulse Data Lake"
    environment: str = "development"
    log_level: str = "INFO"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "velib"
    s3_secret_key: str = "velib-secret"
    s3_region: str = "eu-west-3"
    s3_raw_bucket: str = "raw"

    database_url: str = "postgresql+psycopg2://velib:velib@localhost:5432/velib"

    velib_status_url: str = (
        "https://velib-metropole-opendata.smovengo.cloud/"
        "opendata/Velib_Metropole/station_status.json"
    )
    reference_csv_path: Path = Path("data/source/stations_reference.csv")
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    default_page_size: int = Field(default=100, ge=1, le=1000)
    max_page_size: int = Field(default=1000, ge=1, le=10000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
