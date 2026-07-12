from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models import StationStatusInput
from src.transformations import (
    curate_naive,
    curate_vectorized,
    inputs_to_staging,
    parse_gbfs_payload,
    parse_reference_csv,
)


def test_parse_reference_csv_accepts_technical_columns() -> None:
    content = (
        "stationcode;name;capacity;coordonnees_geo;station_opening_hours\n"
        "123;République;42;48.867, 2.364;\n"
    ).encode()

    records = parse_reference_csv(content)

    assert records[0]["station_code"] == "123"
    assert records[0]["capacity"] == 42
    assert records[0]["latitude"] == 48.867


def test_parse_reference_csv_rejects_bad_coordinates() -> None:
    content = b"stationcode;name;capacity;coordonnees_geo\n123;Test;20;not-a-coordinate\n"
    with pytest.raises(ValueError, match="ligne 2"):
        parse_reference_csv(content)


def test_parse_gbfs_payload_handles_types_and_fallback() -> None:
    payload = {
        "data": {
            "stations": [
                {
                    "stationCode": "A",
                    "num_bikes_available": 7,
                    "num_bikes_available_types": [{"mechanical": 5}, {"ebike": 2}],
                    "num_docks_available": 3,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                    "last_reported": 1_700_000_000,
                },
                {
                    "stationCode": "B",
                    "numBikesAvailable": 4,
                    "numDocksAvailable": 6,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                },
            ]
        }
    }

    rows = parse_gbfs_payload(payload)

    assert rows[0]["mechanical_bikes"] == 5
    assert rows[0]["electric_bikes"] == 2
    assert rows[1]["mechanical_bikes"] == 4
    assert rows[1]["bikes_available"] == 4


def test_parse_gbfs_payload_requires_station_list() -> None:
    with pytest.raises(ValueError, match="data.stations"):
        parse_gbfs_payload({"data": {}})


def _snapshots():
    now = datetime(2026, 7, 12, tzinfo=UTC)
    inputs = [
        StationStatusInput(
            station_code="balanced",
            observed_at=now,
            mechanical_bikes=5,
            electric_bikes=5,
            docks_available=10,
        ),
        StationStatusInput(
            station_code="empty",
            observed_at=now,
            mechanical_bikes=0,
            electric_bikes=0,
            docks_available=20,
        ),
        StationStatusInput(
            station_code="full",
            observed_at=now,
            mechanical_bikes=19,
            electric_bikes=1,
            docks_available=0,
        ),
        StationStatusInput(
            station_code="offline",
            observed_at=now,
            mechanical_bikes=5,
            electric_bikes=0,
            docks_available=5,
            is_renting=False,
        ),
    ]
    return inputs_to_staging(inputs)


def test_naive_and_vectorized_curations_are_equivalent() -> None:
    snapshots = _snapshots()
    references = {
        row["station_code"]: {
            "name": row["station_code"].title(),
            "capacity": 20,
            "latitude": 48.85,
            "longitude": 2.35,
        }
        for row in snapshots
    }

    naive = curate_naive(snapshots, references)
    vectorized = curate_vectorized(snapshots, references)

    ignored = {"calculated_at"}
    assert [
        {key: value for key, value in item.items() if key not in ignored} for item in naive
    ] == [
        {key: value for key, value in item.items() if key not in ignored}
        for item in vectorized
    ]
    assert [row["service_state"] for row in naive] == [
        "balanced",
        "bikes_shortage",
        "docks_shortage",
        "offline",
    ]
    assert [row["alert_level"] for row in naive] == [
        "normal",
        "critical",
        "critical",
        "critical",
    ]


def test_input_rejects_negative_counter_and_unknown_field() -> None:
    with pytest.raises(ValueError):
        StationStatusInput(
            station_code="A",
            mechanical_bikes=-1,
            electric_bikes=0,
            docks_available=1,
        )
    with pytest.raises(ValueError):
        StationStatusInput(
            station_code="A",
            mechanical_bikes=1,
            electric_bikes=0,
            docks_available=1,
            unexpected=True,
        )

