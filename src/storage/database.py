from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from src.config import Settings

metadata = MetaData()

station_reference = Table(
    "station_reference",
    metadata,
    Column("station_code", String(32), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("capacity", Integer, nullable=False),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
    Column("source_ingested_at", DateTime(timezone=True), nullable=False),
    schema="staging",
)

station_snapshot = Table(
    "station_snapshot",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("station_code", String(32), nullable=False, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("mechanical_bikes", Integer, nullable=False),
    Column("electric_bikes", Integer, nullable=False),
    Column("bikes_available", Integer, nullable=False),
    Column("docks_available", Integer, nullable=False),
    Column("is_installed", Boolean, nullable=False),
    Column("is_renting", Boolean, nullable=False),
    Column("is_returning", Boolean, nullable=False),
    Column("source", String(32), nullable=False),
    Column("source_row", Integer, nullable=False),
    UniqueConstraint("station_code", "observed_at", "source", name="uq_snapshot_event"),
    schema="staging",
)

station_kpi = Table(
    "station_kpi",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("station_code", String(32), nullable=False, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("station_name", String(255), nullable=False),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("reference_capacity", Integer, nullable=False),
    Column("bikes_available", Integer, nullable=False),
    Column("docks_available", Integer, nullable=False),
    Column("availability_rate", Float, nullable=False),
    Column("dock_rate", Float, nullable=False),
    Column("ebike_share", Float, nullable=False),
    Column("pressure_score", Float, nullable=False),
    Column("service_state", String(32), nullable=False, index=True),
    Column("alert_level", String(16), nullable=False, index=True),
    Column("calculated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("station_code", "observed_at", name="uq_station_kpi_event"),
    schema="curated",
)


class Database:
    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        self.engine = engine or create_engine(settings.database_url, pool_pre_ping=True)

    @contextmanager
    def begin(self):
        with self.engine.begin() as connection:
            yield connection

    def initialize(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS curated"))
        metadata.create_all(self.engine)

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def upsert_references(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        statement = pg_insert(station_reference).values(records)
        statement = statement.on_conflict_do_update(
            index_elements=[station_reference.c.station_code],
            set_={
                "name": statement.excluded.name,
                "capacity": statement.excluded.capacity,
                "latitude": statement.excluded.latitude,
                "longitude": statement.excluded.longitude,
                "source_ingested_at": statement.excluded.source_ingested_at,
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
        return len(records)

    def reference_map(self) -> dict[str, dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(station_reference)).mappings().all()
        return {row["station_code"]: dict(row) for row in rows}

    @staticmethod
    def _insert_ignore(connection: Connection, table: Table, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        statement = pg_insert(table).values(records).on_conflict_do_nothing()
        result = connection.execute(statement)
        return max(0, result.rowcount or 0)

    def insert_snapshots_bulk(self, records: list[dict[str, Any]]) -> int:
        with self.engine.begin() as connection:
            return self._insert_ignore(connection, station_snapshot, records)

    def insert_curated_bulk(self, records: list[dict[str, Any]]) -> int:
        with self.engine.begin() as connection:
            return self._insert_ignore(connection, station_kpi, records)

    def insert_snapshots_one_by_one(self, records: list[dict[str, Any]]) -> int:
        inserted = 0
        with self.engine.begin() as connection:
            for record in records:
                inserted += self._insert_ignore(connection, station_snapshot, [record])
        return inserted

    def insert_curated_one_by_one(self, records: list[dict[str, Any]]) -> int:
        inserted = 0
        with self.engine.begin() as connection:
            for record in records:
                inserted += self._insert_ignore(connection, station_kpi, [record])
        return inserted

    @staticmethod
    def _serialize_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key, value in item.items():
                if isinstance(value, datetime):
                    item[key] = value.isoformat()
            result.append(item)
        return result

    def get_staging(
        self, limit: int, offset: int, station_code: str | None = None
    ) -> list[dict[str, Any]]:
        statement = select(station_snapshot).order_by(station_snapshot.c.observed_at.desc())
        if station_code:
            statement = statement.where(station_snapshot.c.station_code == station_code)
        statement = statement.limit(limit).offset(offset)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return self._serialize_rows(rows)

    def get_curated(
        self,
        limit: int,
        offset: int,
        station_code: str | None = None,
        alert_level: str | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(station_kpi).order_by(station_kpi.c.observed_at.desc())
        if station_code:
            statement = statement.where(station_kpi.c.station_code == station_code)
        if alert_level:
            statement = statement.where(station_kpi.c.alert_level == alert_level)
        statement = statement.limit(limit).offset(offset)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return self._serialize_rows(rows)

    def stats(self) -> dict[str, int]:
        with self.engine.connect() as connection:
            references = connection.scalar(select(func.count()).select_from(station_reference)) or 0
            staging = connection.scalar(select(func.count()).select_from(station_snapshot)) or 0
            curated = connection.scalar(select(func.count()).select_from(station_kpi)) or 0
        return {
            "reference_rows": int(references),
            "staging_rows": int(staging),
            "curated_rows": int(curated),
        }

