from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.api import app
from src.dependencies import get_service
from src.models import IngestResponse


@dataclass
class FakeObject:
    key: str = "api/2026/status.json"
    size: int = 42
    last_modified: datetime = datetime(2026, 7, 12, tzinfo=UTC)
    etag: str = "abc"


class FakeStore:
    def list_objects(self, prefix: str, limit: int):
        return [FakeObject()] if not prefix or "api".startswith(prefix) else []

    def get_bytes(self, key: str) -> bytes:
        return b'{"ok": true}'


class FakeDatabase:
    def get_staging(self, limit: int, offset: int, station_code: str | None):
        return [{"station_code": station_code or "A"}][:limit]

    def get_curated(
        self,
        limit: int,
        offset: int,
        station_code: str | None,
        alert_level: str | None,
    ):
        return [{"station_code": station_code or "A", "alert_level": alert_level or "normal"}][
            :limit
        ]


class FakeService:
    def __init__(self) -> None:
        self.store = FakeStore()
        self.database = FakeDatabase()
        self.fast_calls: list[bool] = []

    def health(self):
        return {"status": "healthy", "api": "up", "timestamp": "now", "services": {}}

    def stats(self):
        return {"raw": {"objects": 1}, "database": {"curated_rows": 1}}

    def ingest_gateway(self, items, *, fast: bool):
        self.fast_calls.append(fast)
        return IngestResponse(
            mode="fast" if fast else "standard",
            received=len(items),
            staged=len(items),
            curated=len(items),
            raw_key="gateway/test.json",
            duration_ms=1.0,
        )


fake_service = FakeService()
app.dependency_overrides[get_service] = lambda: fake_service
client = TestClient(app)


def test_root_is_personalized() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["author"] == "Jacq VENGADESAN"
    assert response.json()["class"] == "BDML2"


def test_required_read_endpoints() -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/stats").status_code == 200
    assert client.get("/raw").json()["returned"] == 1
    assert client.get("/raw/api/2026/status.json").json() == {"ok": True}
    assert client.get("/staging?station_code=123&limit=5").json()["items"][0][
        "station_code"
    ] == "123"
    assert client.get("/curated?alert_level=critical").json()["items"][0][
        "alert_level"
    ] == "critical"


def test_pagination_is_bounded() -> None:
    assert client.get("/staging?limit=0").status_code == 422
    assert client.get("/curated?limit=1001").status_code == 422


def test_advanced_endpoints_select_expected_strategy() -> None:
    body = {
        "data": [
            {
                "station_code": "A",
                "mechanical_bikes": 2,
                "electric_bikes": 1,
                "docks_available": 4,
            }
        ]
    }
    standard = client.post("/ingest", json=body)
    fast = client.post("/ingest_fast", json=body)
    alias = client.post("/ingest/fast", json=body)

    assert standard.status_code == fast.status_code == alias.status_code == 201
    assert standard.json()["mode"] == "standard"
    assert fast.json()["mode"] == "fast"
    assert fake_service.fast_calls[-3:] == [False, True, True]


def test_ingest_validation_rejects_empty_or_negative_payload() -> None:
    assert client.post("/ingest", json={"data": []}).status_code == 422
    response = client.post(
        "/ingest_fast",
        json={
            "data": [
                {
                    "station_code": "A",
                    "mechanical_bikes": -2,
                    "electric_bikes": 0,
                    "docks_available": 1,
                }
            ]
        },
    )
    assert response.status_code == 422

