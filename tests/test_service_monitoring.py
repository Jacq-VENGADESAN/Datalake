from src.services import DataLakeService


class BrokenStore:
    def ping(self):
        raise ConnectionError("MinIO indisponible")

    def stats(self):
        raise ConnectionError("MinIO indisponible")


class WorkingDatabase:
    def ping(self):
        return None

    def stats(self):
        return {"staging_rows": 12, "curated_rows": 10}


def test_monitoring_survives_partial_failure() -> None:
    service = DataLakeService(settings=None, store=BrokenStore(), database=WorkingDatabase())

    health = service.health()
    stats = service.stats()

    assert health["status"] == "degraded"
    assert health["services"]["minio"]["status"] == "down"
    assert health["services"]["postgresql"]["status"] == "up"
    assert "error" in stats["raw"]
    assert stats["database"]["curated_rows"] == 10

