"""Controlled write operations shared by the MCP write tools and in-app chat proposals (issue #44).

Each write is validated here, executed through `record_edits.py` / `data_store.py` (which guard
against stale edits and append a change-log entry with the given actor), and summarized
compactly. Outside MCP agents call these directly (actor "MCP agent"). The in-app chat never
calls them directly: it turns write requests into proposals that run only after the advisor
confirms (actor "advisor via chat (confirmed)").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from .data_store import UnknownRecommendationError, record_completed_service, update_vehicle_mileage
from .record_edits import (
    REC_STATUSES,
    RecordConflictError,
    RecordValidationError,
    add_recommendation,
    create_vehicle,
    delete_recommendation,
    update_history_entry,
    update_recommendation,
    update_vehicle_details,
)

MCP_ACTOR = "MCP agent"
CHAT_CONFIRMED_ACTOR = "advisor via chat (confirmed)"
MILEAGE_SOURCES = ("advisor_observed", "customer_reported")


class WriteRejected(Exception):
    """The write was not applied; the message explains why (validation, conflict, or unknown record)."""


# ---- Validation helpers ----

def _text(args: dict[str, Any], key: str, max_len: int, required: bool = True) -> str:
    value = args.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise WriteRejected(f"'{key}' must be text.")
    value = value.strip()
    if required and not value:
        raise WriteRejected(f"'{key}' is required.")
    if len(value) > max_len:
        raise WriteRejected(f"'{key}' must be at most {max_len} characters.")
    return value


def _int(args: dict[str, Any], key: str, minimum: int = 0, required: bool = True, maximum: int | None = None) -> int | None:
    value = args.get(key)
    if value is None or value == "":
        if required:
            raise WriteRejected(f"'{key}' is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise WriteRejected(f"'{key}' must be a whole number.")
    if value < minimum or (maximum is not None and value > maximum):
        raise WriteRejected(f"'{key}' must be between {minimum} and {maximum}." if maximum is not None else f"'{key}' must be {minimum} or more.")
    return value


def _past_date(args: dict[str, Any], key: str, required: bool = True) -> str | None:
    value = args.get(key)
    if value in (None, ""):
        if required:
            raise WriteRejected(f"'{key}' is required (YYYY-MM-DD).")
        return None
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise WriteRejected(f"'{key}' must be a date in YYYY-MM-DD format.") from exc
    if parsed > date.today():
        raise WriteRejected(f"'{key}' cannot be in the future.")
    return parsed.isoformat()


def _year(args: dict[str, Any]) -> int:
    return int(_int(args, "year", minimum=1980, maximum=date.today().year + 1))  # type: ignore[arg-type]


def _status(args: dict[str, Any]) -> str:
    status = args.get("status")
    if status not in REC_STATUSES:
        raise WriteRejected(f"'status' must be one of: {', '.join(REC_STATUSES)}.")
    return str(status)


def _index(args: dict[str, Any]) -> int:
    return int(_int(args, "index", minimum=0))  # type: ignore[arg-type]


# ---- Operations ----

def _add_vehicle(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    mileage = _int(args, "mileage", required=False)
    mileage_date = _past_date(args, "mileage_date", required=mileage is not None)
    return create_vehicle(_text(args, "serial", 32), _text(args, "make", 40), _text(args, "model", 40), _year(args),
                          mileage, mileage_date, actor=actor)


def _update_details(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    new_serial = _text(args, "new_serial", 32, required=False) or None
    return update_vehicle_details(_text(args, "serial", 32), _text(args, "make", 40), _text(args, "model", 40),
                                  _year(args), new_serial, actor=actor)


def _update_mileage(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    source = args.get("mileage_source", "advisor_observed")
    if source not in MILEAGE_SOURCES:
        raise WriteRejected(f"'mileage_source' must be one of: {', '.join(MILEAGE_SOURCES)}.")
    return update_vehicle_mileage(_text(args, "serial", 32), int(_int(args, "mileage")),  # type: ignore[arg-type]
                                  _past_date(args, "mileage_date"), str(source), actor=actor)  # type: ignore[arg-type]


def _record_service(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    recommendation = _text(args, "recommendation_name", 120, required=False) or None
    return record_completed_service(_text(args, "serial", 32), _text(args, "service_name", 80),
                                    _past_date(args, "service_date"), _int(args, "mileage", required=False),  # type: ignore[arg-type]
                                    _text(args, "detail", 200, required=False), recommendation, actor=actor)


def _edit_history(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    return update_history_entry(_text(args, "serial", 32), _index(args), _text(args, "expected_date", 40),
                                _text(args, "expected_name", 120), _past_date(args, "service_date"),  # type: ignore[arg-type]
                                _text(args, "name", 80), _text(args, "detail", 200, required=False),
                                _int(args, "mileage", required=False), actor=actor)



def _rec_fields(args: dict[str, Any]) -> tuple[str, str, str, str, str | None, bool]:
    return (_text(args, "name", 80), _status(args), _text(args, "text", 400), _text(args, "evidence", 400),
            _text(args, "rule", 200, required=False) or None, bool(args.get("safety", False)))


def _add_rec(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    return add_recommendation(_text(args, "serial", 32), *_rec_fields(args), actor=actor)


def _update_rec(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    return update_recommendation(_text(args, "serial", 32), _index(args), _text(args, "expected_name", 120),
                                 *_rec_fields(args), actor=actor)


def _remove_rec(args: dict[str, Any], actor: str) -> dict[str, Any] | None:
    return delete_recommendation(_text(args, "serial", 32), _index(args), _text(args, "expected_name", 120), actor=actor)


def _describe(tool: str, a: dict[str, Any]) -> str:
    serial = str(a.get("serial", "?")).upper()
    miles = f" at {a['mileage']:,} mi" if isinstance(a.get("mileage"), int) else ""
    return {
        "add_vehicle": f"Add vehicle {serial}: {a.get('year')} {a.get('make')} {a.get('model')}{miles}",
        "update_vehicle_details": f"Change {serial} details to {a.get('year')} {a.get('make')} {a.get('model')}"
                                  + (f" and rename to {str(a.get('new_serial')).upper()}" if a.get("new_serial") else ""),
        "update_vehicle_mileage": f"Set {serial} current mileage to {a.get('mileage')} mi ({a.get('mileage_date')})",
        "record_completed_service": f"Record '{a.get('service_name')}' done on {serial} on {a.get('service_date')}{miles}"
                                    + (f" and mark '{a.get('recommendation_name')}' Completed" if a.get("recommendation_name") else ""),
        "edit_history_entry": f"Edit {serial} history entry '{a.get('expected_name')}' ({a.get('expected_date')}) → '{a.get('name')}' on {a.get('service_date')}{miles}",
        "add_recommendation": f"Add recommendation '{a.get('name')}' ({a.get('status')}) to {serial}",
        "update_recommendation": f"Change {serial} recommendation '{a.get('expected_name')}' → '{a.get('name')}' ({a.get('status')})",
        "remove_recommendation": f"Remove recommendation '{a.get('expected_name')}' from {serial}",
    }[tool]


WRITE_OPERATIONS: dict[str, Callable[[dict[str, Any], str], dict[str, Any] | None]] = {
    "add_vehicle": _add_vehicle,
    "update_vehicle_details": _update_details,
    "update_vehicle_mileage": _update_mileage,
    "record_completed_service": _record_service,
    "edit_history_entry": _edit_history,
    "add_recommendation": _add_rec,
    "update_recommendation": _update_rec,
    "remove_recommendation": _remove_rec,
}
WRITE_TOOL_NAMES = frozenset(WRITE_OPERATIONS)


def describe_write(tool: str, args: dict[str, Any]) -> str:
    return _describe(tool, args)


def execute_write(tool: str, args: dict[str, Any], actor: str) -> dict[str, Any]:
    """Run one validated write; raise WriteRejected if nothing was saved."""
    operation = WRITE_OPERATIONS.get(tool)
    if operation is None:
        raise WriteRejected(f"Unknown write tool '{tool}'.")
    try:
        vehicle = operation(args, actor)
    except (RecordConflictError, RecordValidationError, UnknownRecommendationError) as exc:
        raise WriteRejected(str(exc)) from exc
    if vehicle is None:
        raise WriteRejected("No synthetic vehicle record found for that serial.")
    log = vehicle.get("changeLog") or []
    return {
        "saved": True,
        "serial": vehicle["serial"],
        "vehicle": {
            "serial": vehicle["serial"], "make": vehicle.get("make"), "model": vehicle.get("model"),
            "year": vehicle.get("year"), "mileage": vehicle.get("mileage"), "completeness": vehicle.get("completeness"),
            "history_count": len(vehicle.get("history") or []),
            "open_recommendations": [r.get("name") for r in vehicle.get("recs") or []
                                     if r.get("status") in ("Due", "Coming up", "Advisor verification")],
        },
        "change": log[-1] if log else None,
    }
