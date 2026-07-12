from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import numpy as np

from src.models import AlertLevel, ServiceState, StationStatusInput


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def parse_reference_csv(content: bytes) -> list[dict[str, Any]]:
    """Normalise le fichier CSV officiel, qu'il utilise des labels FR ou techniques."""

    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    records: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        code = (row.get("stationcode") or row.get("Identifiant station") or "").strip()
        name = (row.get("name") or row.get("Nom station") or "").strip()
        coordinate = row.get("coordonnees_geo") or row.get("Coordonnées géographiques") or ""
        if not code or not name:
            continue
        try:
            lat_text, lon_text = coordinate.split(",", maxsplit=1)
            latitude, longitude = float(lat_text.strip()), float(lon_text.strip())
        except (ValueError, AttributeError) as exc:
            message = f"Coordonnees invalides a la ligne {row_number}: {coordinate!r}"
            raise ValueError(message) from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError(f"Coordonnees hors limites a la ligne {row_number}")
        records.append(
            {
                "station_code": code,
                "name": name,
                "capacity": _as_int(row.get("capacity") or row.get("Capacité")),
                "latitude": latitude,
                "longitude": longitude,
                "source_ingested_at": datetime.now(UTC),
            }
        )
    if not records:
        raise ValueError("Le CSV de reference ne contient aucune station valide")
    return records


def _bike_types(raw_types: Any) -> tuple[int, int]:
    mechanical = electric = 0
    if isinstance(raw_types, list):
        for entry in raw_types:
            if not isinstance(entry, dict):
                continue
            mechanical += _as_int(entry.get("mechanical"))
            electric += _as_int(entry.get("ebike"))
    return mechanical, electric


def parse_gbfs_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convertit le JSON GBFS Velib' en lignes staging strictement typees."""

    stations = payload.get("data", {}).get("stations")
    if not isinstance(stations, list):
        raise ValueError("Payload GBFS invalide: data.stations doit etre une liste")

    result: list[dict[str, Any]] = []
    for index, station in enumerate(stations):
        if not isinstance(station, dict):
            continue
        code = str(station.get("stationCode") or station.get("station_id") or "").strip()
        if not code:
            continue
        mechanical, electric = _bike_types(station.get("num_bikes_available_types"))
        total_reported = _as_int(
            station.get("num_bikes_available", station.get("numBikesAvailable"))
        )
        # Certains producteurs GBFS omettent le detail par type.
        if mechanical + electric == 0 and total_reported > 0:
            mechanical = total_reported
        timestamp = _as_int(station.get("last_reported"))
        observed_at = (
            datetime.fromtimestamp(timestamp, tz=UTC)
            if timestamp > 0
            else datetime.now(UTC)
        )
        result.append(
            {
                "station_code": code,
                "observed_at": observed_at,
                "mechanical_bikes": mechanical,
                "electric_bikes": electric,
                "bikes_available": mechanical + electric,
                "docks_available": _as_int(
                    station.get("num_docks_available", station.get("numDocksAvailable"))
                ),
                "is_installed": bool(station.get("is_installed", 0)),
                "is_renting": bool(station.get("is_renting", 0)),
                "is_returning": bool(station.get("is_returning", 0)),
                "source": "velib_gbfs_api",
                "source_row": index,
            }
        )
    if not result:
        raise ValueError("Le payload GBFS ne contient aucune station exploitable")
    return result


def inputs_to_staging(items: Iterable[StationStatusInput]) -> list[dict[str, Any]]:
    return [
        {
            "station_code": item.station_code,
            "observed_at": item.observed_at,
            "mechanical_bikes": item.mechanical_bikes,
            "electric_bikes": item.electric_bikes,
            "bikes_available": item.bikes_available,
            "docks_available": item.docks_available,
            "is_installed": item.is_installed,
            "is_renting": item.is_renting,
            "is_returning": item.is_returning,
            "source": "gateway",
            "source_row": index,
        }
        for index, item in enumerate(items)
    ]


def _classify(
    bikes: int,
    docks: int,
    is_installed: bool,
    is_renting: bool,
    is_returning: bool,
) -> tuple[str, str]:
    if not (is_installed and is_renting and is_returning):
        return ServiceState.OFFLINE, AlertLevel.CRITICAL
    if bikes == 0:
        return ServiceState.BIKES_SHORTAGE, AlertLevel.CRITICAL
    if docks == 0:
        return ServiceState.DOCKS_SHORTAGE, AlertLevel.CRITICAL
    total = bikes + docks
    ratio = bikes / total if total else 0.0
    if ratio <= 0.15:
        return ServiceState.BIKES_SHORTAGE, AlertLevel.WARNING
    if ratio >= 0.85:
        return ServiceState.DOCKS_SHORTAGE, AlertLevel.WARNING
    return ServiceState.BALANCED, AlertLevel.NORMAL


def curate_naive(
    snapshots: list[dict[str, Any]], references: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Version lisible ligne par ligne, utilisee par /ingest et comme reference."""

    curated: list[dict[str, Any]] = []
    calculated_at = datetime.now(UTC)
    for snapshot in snapshots:
        bikes = _as_int(snapshot["bikes_available"])
        docks = _as_int(snapshot["docks_available"])
        observed_capacity = bikes + docks
        reference = references.get(snapshot["station_code"], {})
        capacity = _as_int(reference.get("capacity")) or observed_capacity
        availability_rate = bikes / observed_capacity if observed_capacity else 0.0
        dock_rate = docks / observed_capacity if observed_capacity else 0.0
        ebike_share = (
            _as_int(snapshot["electric_bikes"]) / bikes if bikes else 0.0
        )
        state, alert = _classify(
            bikes,
            docks,
            bool(snapshot["is_installed"]),
            bool(snapshot["is_renting"]),
            bool(snapshot["is_returning"]),
        )
        curated.append(
            {
                "station_code": snapshot["station_code"],
                "observed_at": snapshot["observed_at"],
                "station_name": reference.get("name", f"Station {snapshot['station_code']}"),
                "latitude": reference.get("latitude"),
                "longitude": reference.get("longitude"),
                "reference_capacity": capacity,
                "bikes_available": bikes,
                "docks_available": docks,
                "availability_rate": round(availability_rate, 6),
                "dock_rate": round(dock_rate, 6),
                "ebike_share": round(ebike_share, 6),
                "pressure_score": round(abs(availability_rate - 0.5) * 2, 6),
                "service_state": str(state),
                "alert_level": str(alert),
                "calculated_at": calculated_at,
            }
        )
    return curated


def curate_vectorized(
    snapshots: list[dict[str, Any]], references: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Version batch NumPy de /ingest_fast, sans boucle de calcul Python."""

    if not snapshots:
        return []
    bikes = np.fromiter((row["bikes_available"] for row in snapshots), dtype=np.int64)
    electric = np.fromiter((row["electric_bikes"] for row in snapshots), dtype=np.int64)
    docks = np.fromiter((row["docks_available"] for row in snapshots), dtype=np.int64)
    installed = np.fromiter((row["is_installed"] for row in snapshots), dtype=bool)
    renting = np.fromiter((row["is_renting"] for row in snapshots), dtype=bool)
    returning = np.fromiter((row["is_returning"] for row in snapshots), dtype=bool)

    totals = bikes + docks
    availability = np.divide(bikes, totals, out=np.zeros_like(bikes, dtype=float), where=totals > 0)
    dock_rates = np.divide(docks, totals, out=np.zeros_like(docks, dtype=float), where=totals > 0)
    ebike_shares = np.divide(
        electric, bikes, out=np.zeros_like(electric, dtype=float), where=bikes > 0
    )
    operational = installed & renting & returning
    states = np.full(len(snapshots), ServiceState.BALANCED.value, dtype=object)
    alerts = np.full(len(snapshots), AlertLevel.NORMAL.value, dtype=object)
    states[~operational] = ServiceState.OFFLINE.value
    alerts[~operational] = AlertLevel.CRITICAL.value
    bike_critical = operational & (bikes == 0)
    dock_critical = operational & (bikes > 0) & (docks == 0)
    states[bike_critical] = ServiceState.BIKES_SHORTAGE.value
    states[dock_critical] = ServiceState.DOCKS_SHORTAGE.value
    alerts[bike_critical | dock_critical] = AlertLevel.CRITICAL.value
    bike_warning = operational & (bikes > 0) & (docks > 0) & (availability <= 0.15)
    dock_warning = operational & (bikes > 0) & (docks > 0) & (availability >= 0.85)
    states[bike_warning] = ServiceState.BIKES_SHORTAGE.value
    states[dock_warning] = ServiceState.DOCKS_SHORTAGE.value
    alerts[bike_warning | dock_warning] = AlertLevel.WARNING.value

    calculated_at = datetime.now(UTC)
    result: list[dict[str, Any]] = []
    for index, snapshot in enumerate(snapshots):
        reference = references.get(snapshot["station_code"], {})
        capacity = _as_int(reference.get("capacity")) or int(totals[index])
        result.append(
            {
                "station_code": snapshot["station_code"],
                "observed_at": snapshot["observed_at"],
                "station_name": reference.get("name", f"Station {snapshot['station_code']}"),
                "latitude": reference.get("latitude"),
                "longitude": reference.get("longitude"),
                "reference_capacity": capacity,
                "bikes_available": int(bikes[index]),
                "docks_available": int(docks[index]),
                "availability_rate": round(float(availability[index]), 6),
                "dock_rate": round(float(dock_rates[index]), 6),
                "ebike_share": round(float(ebike_shares[index]), 6),
                "pressure_score": round(float(abs(availability[index] - 0.5) * 2), 6),
                "service_state": str(states[index]),
                "alert_level": str(alerts[index]),
                "calculated_at": calculated_at,
            }
        )
    return result
