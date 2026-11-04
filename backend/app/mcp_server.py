"""Read-only MCP tools over the synthetic Service Lane Copilot dataset."""

import json
from typing import Any, Literal

from mcp.server import MCPServer

from .data_store import find_vehicle, load_vehicles, search_vehicle_summaries

mcp_server = MCPServer(
    "Service Lane Copilot",
    version="0.1.0",
    instructions=(
        "This server exposes synthetic demo vehicle records only. Treat maintenance rules as fictional examples. "
        "Show the evidence and data limitations. Safety-related entries require advisor verification. "
        "All draft tools are read-only and never send, submit, book, or update records."
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
    """Retrieve one synthetic vehicle record, service history, and recorded demo recommendations."""
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
        "Service Lane Copilot MCP demo guide. All 250 vehicle records and recommendation rules are synthetic. "
        "Use get_vehicle_record to inspect evidence. Unknown, missing, stale, or conflicting data must remain uncertain. "
        "Safety-related items are verification prompts, not diagnoses. Service history is synthetic and is not retrieved "
        "from OBD-II/CAN. Draft tools never send messages or change records."
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
    """Report the count and source boundary of the local vehicle dataset."""
    return {
        "synthetic_data": True,
        "record_count": len(load_vehicles()),
        "source": "data/vehicles.json",
        "live_vehicle_access": False,
        "live_dealership_access": False,
    }


mcp_http_app = mcp_server.streamable_http_app(streamable_http_path="/")


if __name__ == "__main__":
    # MCP-compatible hosts can launch this module as a local stdio subprocess.
    mcp_server.run(transport="stdio")
