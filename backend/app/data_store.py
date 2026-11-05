"""Shared access to the local synthetic dataset and advisor mileage updates."""

import json
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = PROJECT_ROOT / "data" / "vehicles.json"
_DATA_WRITE_LOCK = Lock()


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


def update_vehicle_mileage(
    serial: str,
    mileage: int,
    mileage_date: str,
    mileage_source: str,
) -> dict[str, Any] | None:
    """Replace a known synthetic record's current mileage and persist provenance."""
    normalized = serial.strip().upper()
    with _DATA_WRITE_LOCK:
        vehicles = load_vehicles()
        current = vehicles.get(normalized)
        if current is None:
            return None
        if current.get("mileage") is not None:
            raise ValueError("Manual entry is only available when current mileage is missing.")

        history_miles = []
        for event in current.get("history", []):
            raw_mileage = str(event.get("mileage", ""))
            digits = re.sub(r"[^0-9]", "", raw_mileage)
            if digits:
                history_miles.append(int(digits))

        has_conflict = bool(history_miles and mileage < max(history_miles))
        updated = dict(current)
        updated["mileage"] = mileage
        updated["mileageDate"] = mileage_date
        updated["mileageSource"] = mileage_source
        updated["conflicting"] = has_conflict
        if has_conflict:
            updated["completeness"] = "Conflicting mileage"

        updated_vehicles = dict(vehicles)
        updated_vehicles[normalized] = updated
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=DATA_FILE.parent,
                prefix=".vehicles-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(updated_vehicles, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
            os.replace(temporary_path, DATA_FILE)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

        load_vehicles.cache_clear()
        return updated
