"""Supabase-backed vehicle record access for REST and MCP."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
VEHICLE_TABLE = "vehicle_records"
_DATA_WRITE_LOCK = Lock()


class VehicleStoreUnavailableError(RuntimeError):
    """Supabase is missing, unreachable, or has an invalid vehicle record."""


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Create a backend-only client from environment or the ignored backend/.env."""
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise VehicleStoreUnavailableError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env."
        )
    try:
        return create_client(url, key)
    except Exception as exc:
        raise VehicleStoreUnavailableError(
            "Could not initialize the Supabase vehicle database client."
        ) from exc


def _execute(query: Any) -> list[dict[str, Any]]:
    try:
        response = query.execute()
    except Exception as exc:
        raise VehicleStoreUnavailableError(
            "Supabase vehicle database is unavailable. Check the database URL, key, migration, and network."
        ) from exc
    rows = getattr(response, "data", None)
    if not isinstance(rows, list):
        raise VehicleStoreUnavailableError(
            "Supabase returned an invalid vehicle-record response."
        )
    return rows


def _validated_record(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    serial = row.get("serial")
    record = row.get("record")
    if (
        not isinstance(serial, str)
        or not serial
        or serial != serial.strip().upper()
        or not isinstance(record, dict)
        or record.get("serial") != serial
        or not isinstance(record.get("history"), list)
        or not isinstance(record.get("recs"), list)
    ):
        raise VehicleStoreUnavailableError(
            "Supabase contains an invalid vehicle record. Re-seed or repair the database."
        )
    return serial, record


def load_vehicles() -> dict[str, dict[str, Any]]:
    """Load the current Supabase records for dataset summaries and vehicle search."""
    rows = _execute(
        get_supabase_client().table(VEHICLE_TABLE).select("serial,record").order("serial")
    )
    vehicles: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise VehicleStoreUnavailableError(
                "Supabase returned an invalid vehicle record."
            )
        serial, record = _validated_record(row)
        vehicles[serial] = record
    return vehicles


def find_vehicle(serial: str) -> dict[str, Any] | None:
    """Find one vehicle by its normalized serial key."""
    normalized = serial.strip().upper()
    if not normalized:
        return None
    rows = _execute(
        get_supabase_client()
        .table(VEHICLE_TABLE)
        .select("serial,record")
        .eq("serial", normalized)
        .limit(1)
    )
    if not rows:
        return None
    if not isinstance(rows[0], dict):
        raise VehicleStoreUnavailableError(
            "Supabase returned an invalid vehicle record."
        )
    return _validated_record(rows[0])[1]


OPEN_REC_STATUSES = {"Due", "Coming up", "Advisor verification"}


def list_vehicle_summaries(query: str = "", limit: int = 25, offset: int = 0) -> tuple[int, list[dict[str, Any]]]:
    """Return (total matches, one page of summaries) ordered by serial, for the records view.

    Matches serial, make, model, or year (case-insensitive). Read-only.
    """
    term = query.strip().casefold()
    matches = []
    for vehicle in sorted(load_vehicles().values(), key=lambda item: item["serial"]):
        searchable = " ".join(
            str(vehicle.get(field, "")) for field in ("serial", "make", "model", "year")
        ).casefold()
        if term and term not in searchable:
            continue
        recs = vehicle.get("recs") or []
        matches.append(
            {
                "serial": vehicle["serial"],
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
                "year": vehicle.get("year"),
                "mileage": vehicle.get("mileage"),
                "completeness": vehicle.get("completeness"),
                "incomplete": bool(vehicle.get("incomplete")),
                "conflicting": bool(vehicle.get("conflicting")),
                "open_recommendations": sum(1 for rec in recs if rec.get("status") in OPEN_REC_STATUSES),
                "history_count": len(vehicle.get("history") or []),
            }
        )
    return len(matches), matches[offset : offset + limit]


def search_vehicle_summaries(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Return small summaries matching serial, make, model, or year."""
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
    """Replace a known record's mileage and provenance in Supabase."""
    normalized = serial.strip().upper()
    if not normalized:
        return None
    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None

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

        try:
            result = (
                get_supabase_client()
                .table(VEHICLE_TABLE)
                .update(
                    {
                        "record": updated,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("serial", normalized)
                .select("serial")
                .execute()
            )
        except Exception as exc:
            raise VehicleStoreUnavailableError(
                "Supabase could not save the mileage update."
            ) from exc
        changed_rows = getattr(result, "data", None)
        if not isinstance(changed_rows, list):
            raise VehicleStoreUnavailableError(
                "Supabase returned an invalid mileage-update response."
            )
        if not changed_rows:
            return None
        return updated


class UnknownRecommendationError(ValueError):
    """The completed service names a recommendation that is not on the record."""


HISTORY_DATE_FORMAT = "%b %d, %Y"


def _history_date(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), HISTORY_DATE_FORMAT)
    except ValueError:
        return None


def record_completed_service(
    serial: str,
    service_name: str,
    service_date: str,
    mileage: int | None,
    detail: str = "",
    recommendation_name: str | None = None,
) -> dict[str, Any] | None:
    """Record an advisor-completed service in a known record and save it to Supabase.

    Adds a newest-first history event, optionally marks one stored recommendation
    Completed, and raises current mileage when the service odometer is higher.
    Never calculates a next-due interval. Returns None for an unknown serial.
    """
    normalized = serial.strip().upper()
    if not normalized:
        return None
    performed = datetime.strptime(service_date, "%Y-%m-%d")
    display_date = performed.strftime(HISTORY_DATE_FORMAT)
    mileage_text = "Not recorded" if mileage is None else f"{mileage:,} mi"

    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None

        recs = [dict(rec) for rec in current.get("recs", [])]
        if recommendation_name is not None:
            matches = [rec for rec in recs if rec.get("name") == recommendation_name]
            if not matches:
                raise UnknownRecommendationError(
                    "That recommendation is not on this vehicle record."
                )
            for rec in matches:
                rec["status"] = "Completed"
                rec["kind"] = "done"
                rec["text"] = f"Recorded as completed by the advisor on {display_date}."
                rec["evidence"] = f"Completed {display_date} at {mileage_text} · Advisor-recorded service"

        event = {
            "date": display_date,
            "name": service_name,
            "detail": detail or "Advisor-recorded completed service",
            "mileage": mileage_text,
            "source": "advisor_recorded",
        }
        history = list(current.get("history", []))
        insert_at = len(history)
        for index, existing in enumerate(history):
            existing_date = _history_date(existing.get("date"))
            if existing_date is not None and existing_date <= performed:
                insert_at = index
                break
        history.insert(insert_at, event)

        updated = dict(current)
        updated["history"] = history
        updated["recs"] = recs
        current_mileage = current.get("mileage")
        if mileage is not None and (current_mileage is None or mileage > current_mileage):
            updated["mileage"] = mileage
            updated["mileageDate"] = service_date
            updated["mileageSource"] = "advisor_observed"

        history_miles = [
            int(digits)
            for digits in (re.sub(r"[^0-9]", "", str(item.get("mileage", ""))) for item in history)
            if digits
        ]
        if updated.get("mileage") is not None:
            has_conflict = bool(history_miles and updated["mileage"] < max(history_miles))
            updated["conflicting"] = has_conflict
            if has_conflict:
                updated["completeness"] = "Conflicting mileage"

        try:
            result = (
                get_supabase_client()
                .table(VEHICLE_TABLE)
                .update(
                    {
                        "record": updated,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("serial", normalized)
                .select("serial")
                .execute()
            )
        except Exception as exc:
            raise VehicleStoreUnavailableError(
                "Supabase could not save the completed service."
            ) from exc
        changed_rows = getattr(result, "data", None)
        if not isinstance(changed_rows, list):
            raise VehicleStoreUnavailableError(
                "Supabase returned an invalid completed-service response."
            )
        if not changed_rows:
            return None
        return updated
