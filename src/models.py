from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertLevel(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class ServiceState(StrEnum):
    BALANCED = "balanced"
    BIKES_SHORTAGE = "bikes_shortage"
    DOCKS_SHORTAGE = "docks_shortage"
    OFFLINE = "offline"


class StationStatusInput(BaseModel):
    """Statut unifie accepte par les endpoints d'ingestion avancee."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    station_code: str = Field(min_length=1, max_length=32)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mechanical_bikes: int = Field(ge=0)
    electric_bikes: int = Field(ge=0)
    docks_available: int = Field(ge=0)
    is_installed: bool = True
    is_renting: bool = True
    is_returning: bool = True

    @model_validator(mode="after")
    def normalize_timestamp(self) -> StationStatusInput:
        if self.observed_at.tzinfo is None:
            self.observed_at = self.observed_at.replace(tzinfo=UTC)
        else:
            self.observed_at = self.observed_at.astimezone(UTC)
        return self

    @property
    def bikes_available(self) -> int:
        return self.mechanical_bikes + self.electric_bikes


class IngestRequest(BaseModel):
    data: list[StationStatusInput] = Field(min_length=1, max_length=10_000)


class IngestResponse(BaseModel):
    mode: str
    received: int
    staged: int
    curated: int
    raw_key: str
    duration_ms: float


class PaginatedResponse(BaseModel):
    items: list[dict]
    limit: int
    offset: int
    returned: int

