"""Add vehicles and edit vehicle records (issue #42).

Every function validates against the current record, writes through the same Supabase
client and lock as the other data-store writes, appends a change-log entry, and returns
the updated record (None for an unknown serial). Failures leave the record unchanged.
The `actor` argument lets the MCP write tools reuse these functions in a later ticket.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .data_store import (
    _DATA_WRITE_LOCK,
    HISTORY_DATE_FORMAT,
    NEW_RECORD_COMPLETENESS,
    VEHICLE_TABLE,
    WEB_ACTOR,
    VehicleStoreUnavailableError,
    _history_date,
    append_change,
    find_vehicle,
    get_supabase_client,
)

SERIAL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,30}[A-Z0-9]$")
REC_STATUSES = {"Due": "due", "Coming up": "soon", "Advisor verification": "safety", "Not yet due": "neutral"}


class RecordConflictError(Exception):
    """The request conflicts with the current record (duplicate serial or stale entry) → HTTP 409."""


class RecordValidationError(ValueError):
    """The request is not valid for this record → HTTP 422."""


def normalize_serial(serial: str) -> str:
    normalized = serial.strip().upper()
    if not SERIAL_PATTERN.match(normalized):
        raise RecordValidationError(
            "Serial must be 3–32 characters of letters, digits, or hyphens, starting and ending with a letter or digit."
        )
    return normalized


def _mileage_text(mileage: int | None) -> str:
    return "Not recorded" if mileage is None else f"{mileage:,} mi"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refresh_conflict(record: dict[str, Any]) -> None:
    """Same rule as the mileage route: current mileage below a recorded service mileage is a conflict."""
    current = record.get("mileage")
    miles = [int(d) for d in (re.sub(r"\D", "", str(e.get("mileage", ""))) for e in record.get("history", [])) if d]
    if current is None:
        return
    conflict = bool(miles and current < max(miles))
    record["conflicting"] = conflict
    if conflict:
        record["completeness"] = "Conflicting mileage"
        record["incomplete"] = True


def _save(serial: str, record: dict[str, Any], action_label: str) -> None:
    try:
        result = (
            get_supabase_client().table(VEHICLE_TABLE)
            .update({"record": record, "updated_at": _now()})
            .eq("serial", serial).select("serial").execute()
        )
    except Exception as exc:
        raise VehicleStoreUnavailableError(f"Supabase could not save the {action_label}.") from exc
    if not isinstance(getattr(result, "data", None), list) or not result.data:
        raise VehicleStoreUnavailableError(f"Supabase did not confirm the {action_label}.")


def _insert(serial: str, record: dict[str, Any], action_label: str) -> None:
    try:
        result = get_supabase_client().table(VEHICLE_TABLE).insert(
            {"serial": serial, "record": record, "updated_at": _now()}
        ).execute()
    except Exception as exc:
        raise VehicleStoreUnavailableError(f"Supabase could not save the {action_label}.") from exc
    if not isinstance(getattr(result, "data", None), list) or not result.data:
        raise VehicleStoreUnavailableError(f"Supabase did not confirm the {action_label}.")


def _delete(serial: str) -> None:
    try:
        get_supabase_client().table(VEHICLE_TABLE).delete().eq("serial", serial).execute()
    except Exception as exc:
        raise VehicleStoreUnavailableError(
            "The vehicle was saved under its new serial, but the old serial could not be removed. Remove it manually."
        ) from exc


def _guarded_index(items: list[dict[str, Any]], index: int, kind: str) -> dict[str, Any]:
    if not 0 <= index < len(items):
        raise RecordConflictError(f"That {kind} no longer exists. Reload the record and try again.")
    return items[index]


def _sort_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first; entries with unreadable dates keep their relative order at the end."""
    dated = [(i, _history_date(e.get("date"))) for i, e in enumerate(history)]
    known = sorted((d for d in dated if d[1] is not None), key=lambda d: d[1], reverse=True)
    unknown = [d for d in dated if d[1] is None]
    return [history[i] for i, _ in known + unknown]


# ---- Vehicles ----

def create_vehicle(
    serial: str, make: str, model: str, year: int,
    mileage: int | None = None, mileage_date: str | None = None, actor: str = WEB_ACTOR,
) -> dict[str, Any]:
    normalized = normalize_serial(serial)
    record: dict[str, Any] = {
        "serial": normalized, "make": make, "model": model, "year": year,
        "mileage": mileage,
        "mileageDate": mileage_date if mileage is not None and mileage_date else "Mileage not recorded",
        "completeness": NEW_RECORD_COMPLETENESS,
        "history": [], "recs": [], "incomplete": True, "conflicting": False,
    }
    if mileage is not None:
        record["mileageSource"] = "advisor_observed"
    append_change(record, "vehicle_created", f"Added {year} {make} {model} ({normalized}).", actor)
    with _DATA_WRITE_LOCK:
        if find_vehicle(normalized) is not None:
            raise RecordConflictError(f"A vehicle with serial {normalized} already exists.")
        _insert(normalized, record, "new vehicle")
    return record


def update_vehicle_details(
    serial: str, make: str, model: str, year: int, new_serial: str | None = None, actor: str = WEB_ACTOR,
) -> dict[str, Any] | None:
    current_serial = serial.strip().upper()
    target = normalize_serial(new_serial) if new_serial else current_serial
    with _DATA_WRITE_LOCK:
        current = find_vehicle(current_serial)
        if current is None:
            return None
        changes = [
            f"{label} {old!r} → {new!r}"
            for label, old, new in (("make", current.get("make"), make), ("model", current.get("model"), model),
                                    ("year", current.get("year"), year), ("serial", current_serial, target))
            if old != new
        ]
        if not changes:
            return current
        updated = {**current, "make": make, "model": model, "year": year, "serial": target}
        append_change(updated, "vehicle_details_updated", "Changed " + "; ".join(changes) + ".", actor)
        if target == current_serial:
            _save(current_serial, updated, "vehicle details")
        else:
            if find_vehicle(target) is not None:
                raise RecordConflictError(f"A vehicle with serial {target} already exists.")
            _insert(target, updated, "renamed vehicle")
            _delete(current_serial)
    return updated


# ---- Service history ----

def _check_expected_history(entry: dict[str, Any], expected_date: str, expected_name: str) -> None:
    if entry.get("date") != expected_date or entry.get("name") != expected_name:
        raise RecordConflictError("That history entry changed since the page loaded. Reload the record and try again.")


def update_history_entry(
    serial: str, index: int, expected_date: str, expected_name: str,
    service_date: str, name: str, detail: str, mileage: int | None, actor: str = WEB_ACTOR,
) -> dict[str, Any] | None:
    normalized = serial.strip().upper()
    display = datetime.strptime(service_date, "%Y-%m-%d").strftime(HISTORY_DATE_FORMAT)
    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None
        history = [dict(e) for e in current.get("history", [])]
        entry = _guarded_index(history, index, "history entry")
        _check_expected_history(entry, expected_date, expected_name)
        replacement = {**entry, "date": display, "name": name, "detail": detail or entry.get("detail", ""),
                       "mileage": _mileage_text(mileage), "source": entry.get("source", "dealer_record"), "edited": True}
        history[index] = replacement
        updated = {**current, "history": _sort_history(history)}
        _refresh_conflict(updated)
        append_change(updated, "history_entry_updated",
                      f"Edited history entry '{expected_name}' ({expected_date}) → '{name}' on {display} at {_mileage_text(mileage)}.", actor)
        _save(normalized, updated, "history edit")
    return updated


def delete_history_entry(
    serial: str, index: int, expected_date: str, expected_name: str, actor: str = WEB_ACTOR,
) -> dict[str, Any] | None:
    normalized = serial.strip().upper()
    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None
        history = [dict(e) for e in current.get("history", [])]
        entry = _guarded_index(history, index, "history entry")
        _check_expected_history(entry, expected_date, expected_name)
        del history[index]
        updated = {**current, "history": history}
        _refresh_conflict(updated)
        append_change(updated, "history_entry_deleted",
                      f"Deleted history entry '{expected_name}' ({expected_date}, {entry.get('mileage')}).", actor)
        _save(normalized, updated, "history deletion")
    return updated


# ---- Recommendations ----

def _advisor_recommendation(name: str, status: str, text: str, evidence: str, rule: str | None, safety: bool) -> dict[str, Any]:
    if status not in REC_STATUSES:
        raise RecordValidationError(f"Status must be one of: {', '.join(REC_STATUSES)}.")
    return {
        "name": name, "status": status, "kind": REC_STATUSES[status], "text": text, "evidence": evidence,
        "rule": rule or "Advisor-entered recommendation; not from the demo schedule.",
        "safety": safety, "source": "advisor_entered",
    }


def add_recommendation(
    serial: str, name: str, status: str, text: str, evidence: str,
    rule: str | None = None, safety: bool = False, actor: str = WEB_ACTOR,
) -> dict[str, Any] | None:
    normalized = serial.strip().upper()
    rec = _advisor_recommendation(name, status, text, evidence, rule, safety)
    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None
        recs = [dict(r) for r in current.get("recs", [])]
        if any(r.get("name", "").strip().lower() == name.strip().lower() and r.get("kind") != "done" for r in recs):
            raise RecordConflictError(f"An open recommendation named '{name}' already exists. Edit it instead.")
        updated = {**current, "recs": [*recs, rec]}
        append_change(updated, "recommendation_added", f"Added recommendation '{name}' ({status}).", actor)
        _save(normalized, updated, "recommendation")
    return updated


def update_recommendation(
    serial: str, index: int, expected_name: str, name: str, status: str, text: str, evidence: str,
    rule: str | None = None, safety: bool = False, actor: str = WEB_ACTOR,
) -> dict[str, Any] | None:
    normalized = serial.strip().upper()
    rec = _advisor_recommendation(name, status, text, evidence, rule, safety)
    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None
        recs = [dict(r) for r in current.get("recs", [])]
        existing = _guarded_index(recs, index, "recommendation")
        if existing.get("name") != expected_name:
            raise RecordConflictError("That recommendation changed since the page loaded. Reload the record and try again.")
        recs[index] = rec
        updated = {**current, "recs": recs}
        append_change(updated, "recommendation_updated",
                      f"Edited recommendation '{expected_name}' ({existing.get('status')}) → '{name}' ({status}).", actor)
        _save(normalized, updated, "recommendation edit")
    return updated


def delete_recommendation(serial: str, index: int, expected_name: str, actor: str = WEB_ACTOR) -> dict[str, Any] | None:
    normalized = serial.strip().upper()
    with _DATA_WRITE_LOCK:
        current = find_vehicle(normalized)
        if current is None:
            return None
        recs = [dict(r) for r in current.get("recs", [])]
        existing = _guarded_index(recs, index, "recommendation")
        if existing.get("name") != expected_name:
            raise RecordConflictError("That recommendation changed since the page loaded. Reload the record and try again.")
        del recs[index]
        updated = {**current, "recs": recs}
        append_change(updated, "recommendation_removed", f"Removed recommendation '{expected_name}' ({existing.get('status')}).", actor)
        _save(normalized, updated, "recommendation removal")
    return updated
