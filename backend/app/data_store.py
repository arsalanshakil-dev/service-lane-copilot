"""Shared, read-only access to the synthetic vehicle dataset."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = PROJECT_ROOT / "data" / "vehicles.json"


@lru_cache(maxsize=1)
def load_vehicles() -> dict[str, dict[str, Any]]:
    """Load and validate the synthetic dataset once per process."""
    try:
        with DATA_FILE.open("r", encoding="utf-8") as data_file:
            vehicles = json.load(data_file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Synthetic vehicle dataset not found: {DATA_FILE}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Synthetic vehicle dataset is not valid JSON: {DATA_FILE}") from exc

    if not isinstance(vehicles, dict):
        raise RuntimeError("Synthetic vehicle dataset must be an object keyed by serial number.")

    for serial, record in vehicles.items():
        if not isinstance(record, dict) or record.get("serial") != serial:
            raise RuntimeError(f"Invalid vehicle record for serial {serial!r}.")
        if not isinstance(record.get("history"), list) or not isinstance(record.get("recs"), list):
            raise RuntimeError(f"Vehicle record {serial!r} must contain history and recs lists.")

    return vehicles


def find_vehicle(serial: str) -> dict[str, Any] | None:
    """Find one vehicle by normalized demo serial/VIN key."""
    return load_vehicles().get(serial.strip().upper())


def search_vehicle_summaries(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Return small synthetic record summaries matching serial, make, or model."""
    term = query.strip().casefold()
    matches = []
    for vehicle in load_vehicles().values():
        searchable = " ".join(
            str(vehicle.get(field, "")) for field in ("serial", "make", "model", "year")
        ).casefold()
        if not term or term in searchable:
            matches.append(
                {
                    "serial": vehicle["serial"],
                    "make": vehicle.get("make"),
                    "model": vehicle.get("model"),
                    "year": vehicle.get("year"),
                    "completeness": vehicle.get("completeness"),
                }
            )
        if len(matches) >= limit:
            break
    return matches
