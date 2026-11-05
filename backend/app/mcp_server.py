"""MCP tools over the synthetic Service Lane Copilot dataset.

Read tools and draft tools never change records. Write tools (issue #44) add and edit
synthetic vehicle records through the same validated, change-logged functions as the REST API.
"""

import json
from typing import Any, Literal

from mcp.server import MCPServer

from .data_store import find_vehicle, load_vehicles, search_vehicle_summaries
from .mcp_writes import MCP_ACTOR, WriteRejected, execute_write

mcp_server = MCPServer(
    "Service Lane Copilot",
    version="0.1.0",
    instructions=(
        "This server exposes synthetic demo vehicle records only. Treat maintenance rules as fictional examples. "
        "Vehicle telemetry is deterministic simulated POC data, never live OBD-II. Do not use it as mileage, service-history, diagnostic, or recommendation evidence. "
        "Show the evidence and data limitations. Safety-related entries require advisor verification. "
        "Draft tools never send, submit, book, or update records. Write tools (add_vehicle, update_vehicle_details, "
        "update_vehicle_mileage, record_completed_service, edit_history_entry, add_recommendation, "
        "update_recommendation, remove_recommendation) change synthetic records only when the user clearly asked for that change. "
        "Service history can be corrected with edit_history_entry but never deleted; "
        "read the record first, pass the expected entry for edits, and report the saved change or the returned error. "
        "Every write is recorded in the vehicle's change log."
    ),
)


@mcp_server.tool()
def search_vehicle_records(query: str = "", limit: int = 20) -> dict[str, Any]:
    """Search synthetic vehicle records by serial number, make, or model.

    Returns a limited list of summaries. This tool does not access live dealership systems.
    """
    safe_limit = max(1, min(limit, 100))
    matches = search_vehicle_summaries(query, safe_limit)
    return {
        "synthetic_data": True,
        "count": len(matches),
        "limit": safe_limit,
        "vehicles": matches,
    }


@mcp_server.tool()
def get_vehicle_record(serial: str) -> dict[str, Any]:
    """Retrieve one synthetic vehicle record, simulated-only telemetry, service history, and recorded demo recommendations. Telemetry is not live and is not recommendation evidence."""
    vehicle = find_vehicle(serial)
    if vehicle is None:
        return {
            "found": False,
            "synthetic_data": True,
            "serial": serial.strip().upper(),
            "message": "No synthetic vehicle record found. Do not invent vehicle details or service history.",
        }
    return {"found": True, "synthetic_data": True, "vehicle": vehicle}


@mcp_server.tool()
def create_customer_draft(
    serial: str,
    draft_type: Literal["explanation", "quote", "followup"] = "explanation",
) -> dict[str, Any]:
    """Prepare an editable customer-facing draft. Nothing is sent or submitted."""
    vehicle = find_vehicle(serial)
    if vehicle is None:
        return {
            "found": False,
            "synthetic_data": True,
            "draft_created": False,
            "message": "No synthetic record found. Retrieve or verify vehicle history before drafting a service recommendation.",
        }

    due_items = [
        item["name"]
        for item in vehicle.get("recs", [])
        if item.get("status") in {"Due", "Coming up"}
    ]
    items_text = ", ".join(due_items)
    mileage = vehicle.get("mileage")
    mileage_text = "not available" if mileage is None else f"{mileage:,} mi"
    vehicle_name = f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"

    if draft_type == "explanation":
        if vehicle.get("incomplete") or vehicle.get("conflicting") or mileage is None:
            body = (
                f"Hello, we are checking the service history and mileage for your {vehicle_name} "
                f"({vehicle['serial']}) before confirming what may be due. Your service advisor will review the record."
            )
        else:
            recommendation = (
                f"The following items may be due or coming up: {items_text}."
                if items_text
                else "No items match the current demo examples."
            )
            body = (
                f"Hello, based on the available service history for your {vehicle_name} ({vehicle['serial']}) "
                f"and recorded mileage of {mileage_text}, {recommendation} These are synthetic demo suggestions "
                "that your service advisor should verify."
            )
    elif draft_type == "quote":
        line_items = items_text or "Not determined — verify mileage and history first."
        body = (
            f"Draft quote for advisor review\nVehicle: {vehicle_name} · {vehicle['serial']}\n"
            f"Recorded mileage: {mileage_text}\nSuggested line items: {line_items}\n"
            "Pricing: Add dealership-approved parts and labor pricing before sharing.\n"
            "Demo recommendation only; advisor verification required."
        )
    else:
        body = (
            f"Hello, this is a follow-up draft regarding your {vehicle_name}. "
            f"{f'We reviewed the available history and would like to discuss: {items_text}.' if items_text else 'We are confirming the service history and mileage before making a recommendation.'} "
            "Please contact our service team if you have questions."
        )

    return {
        "found": True,
        "synthetic_data": True,
        "draft_created": True,
        "draft_type": draft_type,
        "sent": False,
        "requires_advisor_review": True,
        "draft_text": body,
    }


@mcp_server.tool()
def create_record_request_draft(
    serial: str,
    request_type: Literal["registration", "outside_history"] = "outside_history",
) -> dict[str, Any]:
    """Prepare an unsent dealership-record intake or outside-history request draft."""
    normalized = serial.strip().upper()
    vehicle = find_vehicle(normalized)
    known_vehicle = (
        f"\nVehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']}"
        if vehicle is not None
        else "\nVehicle details to confirm: make, model, year, and current odometer reading"
    )

    if request_type == "registration":
        text = (
            f"Draft vehicle record intake for advisor review\nSerial number: {normalized}{known_vehicle}\n"
            "Details to confirm: current odometer reading, date recorded, and customer-provided service records.\n"
            "Do not submit until details and customer authorization are confirmed."
        )
    else:
        text = (
            f"Draft request for another dealership to provide service history\nVehicle serial number: {normalized}{known_vehicle}\n"
            "Customer name and authorization: add after verification.\n"
            "Request available service dates, service items performed, recorded mileage, and supporting maintenance documentation.\n"
            "Advisor review: confirm recipient, authorization, and dealership process before sending."
        )

    return {
        "synthetic_data": True,
        "request_type": request_type,
        "sent": False,
        "submitted": False,
        "requires_advisor_review": True,
        "draft_text": text,
    }


@mcp_server.resource("service-lane://demo-guide")
def demo_guide() -> str:
    """Describe the dataset boundaries and recommendation safety rules."""
    return (
        "Service Lane Copilot MCP demo guide. All 1,000 vehicle records and recommendation rules are synthetic. "
        "Vehicle telemetry fields are simulated POC samples only, not live OBD-II readings and not service or recommendation evidence. Use get_vehicle_record to inspect dealership-history evidence. Unknown, missing, stale, or conflicting data must remain uncertain. "
        "Safety-related items are verification prompts, not diagnoses. Service history is synthetic and is not retrieved "
        "from OBD-II/CAN. Draft tools never send messages or change records. Write tools change synthetic records only "
        "when asked, validate input, refuse stale edits, and log every change."
    )


@mcp_server.resource("vehicle://{serial}")
def vehicle_resource(serial: str) -> str:
    """Expose one synthetic vehicle record as a read-only MCP resource."""
    vehicle = find_vehicle(serial)
    if vehicle is None:
        return json.dumps(
            {
                "found": False,
                "synthetic_data": True,
                "serial": serial.strip().upper(),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"found": True, "synthetic_data": True, "vehicle": vehicle},
        ensure_ascii=False,
    )


@mcp_server.tool()
def dataset_summary() -> dict[str, Any]:
    """Report the count and source boundary of the Supabase-backed synthetic records."""
    return {
        "synthetic_data": True,
        "record_count": len(load_vehicles()),
        "source": "Supabase Postgres public.vehicle_records",
        "seed_fixture": "data/vehicles.json",
        "live_vehicle_access": False,
        "live_dealership_access": False,
        "simulated_obd_telemetry_available": True,
    }


# ---- Write tools (issue #44): validated, change-logged edits to synthetic records ----

def _write(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        return execute_write(tool, args, MCP_ACTOR)
    except WriteRejected as exc:
        return {"saved": False, "error": str(exc)}


@mcp_server.tool()
def add_vehicle(serial: str, make: str, model: str, year: int, mileage: int | None = None, mileage_date: str | None = None) -> dict[str, Any]:
    """Add a new synthetic vehicle record. serial: 3-32 letters/digits/hyphens. mileage_date (YYYY-MM-DD) is required when mileage is given. Fails if the serial exists."""
    return _write("add_vehicle", {"serial": serial, "make": make, "model": model, "year": year, "mileage": mileage, "mileage_date": mileage_date})


@mcp_server.tool()
def update_vehicle_details(serial: str, make: str, model: str, year: int, new_serial: str | None = None) -> dict[str, Any]:
    """Change a vehicle's make, model, and year; optionally rename its serial to new_serial (fails if new_serial exists). Pass the current values for fields that should not change."""
    return _write("update_vehicle_details", {"serial": serial, "make": make, "model": model, "year": year, "new_serial": new_serial})


@mcp_server.tool()
def update_vehicle_mileage(serial: str, mileage: int, mileage_date: str, mileage_source: Literal["advisor_observed", "customer_reported"] = "advisor_observed") -> dict[str, Any]:
    """Replace a vehicle's current odometer reading. mileage_date is YYYY-MM-DD and cannot be in the future."""
    return _write("update_vehicle_mileage", {"serial": serial, "mileage": mileage, "mileage_date": mileage_date, "mileage_source": mileage_source})


@mcp_server.tool()
def record_completed_service(serial: str, service_name: str, service_date: str, mileage: int | None = None, detail: str = "", recommendation_name: str | None = None) -> dict[str, Any]:
    """Record a completed service in the vehicle's history (service_date YYYY-MM-DD). If it completes a stored recommendation, pass its exact name as recommendation_name to mark it Completed. A higher mileage also updates current mileage."""
    return _write("record_completed_service", {"serial": serial, "service_name": service_name, "service_date": service_date, "mileage": mileage, "detail": detail, "recommendation_name": recommendation_name})


@mcp_server.tool()
def edit_history_entry(serial: str, index: int, expected_date: str, expected_name: str, service_date: str, name: str, detail: str = "", mileage: int | None = None) -> dict[str, Any]:
    """Replace one service-history entry. index is its 0-based position in get_vehicle_record history; expected_date and expected_name must match that entry exactly (e.g. 'Apr 18, 2026'). service_date is YYYY-MM-DD."""
    return _write("edit_history_entry", {"serial": serial, "index": index, "expected_date": expected_date, "expected_name": expected_name, "service_date": service_date, "name": name, "detail": detail, "mileage": mileage})



@mcp_server.tool()
def add_recommendation(serial: str, name: str, status: Literal["Due", "Coming up", "Advisor verification", "Not yet due"], text: str, evidence: str, rule: str | None = None, safety: bool = False) -> dict[str, Any]:
    """Add an advisor-entered recommendation with the advisor's own explanation (text) and evidence. It is labelled Advisor-entered, not a demo-schedule item."""
    return _write("add_recommendation", {"serial": serial, "name": name, "status": status, "text": text, "evidence": evidence, "rule": rule, "safety": safety})


@mcp_server.tool()
def update_recommendation(serial: str, index: int, expected_name: str, name: str, status: Literal["Due", "Coming up", "Advisor verification", "Not yet due"], text: str, evidence: str, rule: str | None = None, safety: bool = False) -> dict[str, Any]:
    """Replace one recommendation. index is its 0-based position in get_vehicle_record recs and expected_name must match it."""
    return _write("update_recommendation", {"serial": serial, "index": index, "expected_name": expected_name, "name": name, "status": status, "text": text, "evidence": evidence, "rule": rule, "safety": safety})


@mcp_server.tool()
def remove_recommendation(serial: str, index: int, expected_name: str) -> dict[str, Any]:
    """Remove one recommendation. index and expected_name must match the recommendation from get_vehicle_record."""
    return _write("remove_recommendation", {"serial": serial, "index": index, "expected_name": expected_name})


mcp_http_app = mcp_server.streamable_http_app(streamable_http_path="/")


if __name__ == "__main__":
    # MCP-compatible hosts can launch this module as a local stdio subprocess.
    mcp_server.run(transport="stdio")
