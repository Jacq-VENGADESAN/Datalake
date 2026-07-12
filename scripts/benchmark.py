from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx


def make_payload(size: int, run: int) -> dict:
    base = datetime.now(UTC) + timedelta(seconds=run)
    return {
        "data": [
            {
                "station_code": f"BENCH-{index:05d}",
                "observed_at": (base + timedelta(microseconds=index)).isoformat(),
                "mechanical_bikes": (index * 3) % 21,
                "electric_bikes": (index * 7) % 11,
                "docks_available": 30 - ((index * 5) % 25),
                "is_installed": True,
                "is_renting": True,
                "is_returning": True,
            }
            for index in range(size)
        ]
    }


def measure(client: httpx.Client, endpoint: str, size: int, repeats: int) -> list[float]:
    durations = []
    for run in range(repeats):
        started = time.perf_counter()
        response = client.post(endpoint, json=make_payload(size, run))
        response.raise_for_status()
        durations.append((time.perf_counter() - started) * 1000)
    return durations


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark /ingest et /ingest_fast")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/latest.json"))
    args = parser.parse_args()

    report = {"measured_at": datetime.now(UTC).isoformat(), "base_url": args.url}
    with httpx.Client(base_url=args.url, timeout=120) as client:
        # Echauffement de NumPy, des pools SQL et HTTP avant les mesures.
        client.post("/ingest_fast", json=make_payload(2, -1)).raise_for_status()
        for size in (1, 100):
            standard = measure(client, "/ingest", size, args.repeats)
            fast = measure(client, "/ingest_fast", size, args.repeats)
            standard_median = statistics.median(standard)
            fast_median = statistics.median(fast)
            gain = (standard_median - fast_median) / standard_median * 100
            report[str(size)] = {
                "standard_ms": standard,
                "fast_ms": fast,
                "standard_median_ms": round(standard_median, 3),
                "fast_median_ms": round(fast_median, 3),
                "gain_percent": round(gain, 2),
            }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

