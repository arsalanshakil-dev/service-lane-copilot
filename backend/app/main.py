"""REST API and local MCP HTTP mount for the synthetic Service Lane Copilot."""

from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .data_store import find_vehicle, load_vehicles, search_vehicle_summaries, update_vehicle_mileage
from .mcp_server import mcp_server, mcp_http_app


class ManualMileageUpdate(BaseModel):
    """Advisor-confirmed manual odometer reading for a synthetic record."""

    mileage: int = Field(ge=0)
    mileage_date: date = Field(alias="mileageDate")
    mileage_source: Literal["advisor_observed", "customer_reported"] = Field(alias="mileageSource")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Mounted MCP sub-apps do not start their own lifespan; keep the SDK's
    # Streamable HTTP session manager alive for the host FastAPI app.
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(
    title="Service Lane Copilot API",
    version="0.1.0",
    description=(
        "REST API over the 250-record synthetic vehicle dataset. Search and retrieval are read-only; one local route allows an advisor to update missing mileage.\n\n"
        "## REST API\n"
        "Search and retrieve synthetic vehicle records, or enter missing mileage for a known synthetic vehicle. "
        "Unknown serials return 404; no real dealership data is queried.\n\n"
        "## MCP agent access\n"
        "The same dataset is available to MCP-compatible agents over Streamable HTTP at `/mcp` "
        "or through the local stdio launcher. MCP draft tools never send or submit content. "
        "The MCP protocol endpoint is not an OpenAPI route; see `/api/capabilities` for its tools and resources.\n\n"
        "All vehicle, mileage, history, and recommendation content is synthetic demo data."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "Backend overview",
            "description": "Service status and a summary of the REST and MCP interfaces.",
        },
        {
            "name": "Vehicles",
            "description": "Search and retrieval over synthetic records plus an advisor-reviewed local mileage update.",
        },
    ],
    lifespan=lifespan,
)


@app.get("/api/health", tags=["Backend overview"])
def health() -> dict[str, Any]:
    """Return service status and loaded synthetic record count."""
    return {"status": "ok", "synthetic_data": True, "record_count": len(load_vehicles())}


@app.get(
    "/api/capabilities",
    tags=["Backend overview"],
    summary="Describe available backend interfaces",
)
def capabilities() -> dict[str, Any]:
    """Summarize documented REST routes and the MCP interface for this local demo."""
    return {
        "synthetic_data": True,
        "record_count": len(load_vehicles()),
        "rest": {
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/api/health",
            "search_vehicles": "/api/vehicles?q={query}&limit={limit}",
            "get_vehicle": "/api/vehicles/{serial}",
            "update_missing_mileage": "PATCH /api/vehicles/{serial}/mileage",
        },
        "mcp": {
            "streamable_http": "/mcp",
            "stdio_launcher": "backend/mcp_stdio.py",
            "tools": [
                "search_vehicle_records",
                "get_vehicle_record",
                "create_customer_draft",
                "create_record_request_draft",
                "dataset_summary",
            ],
            "resources": ["service-lane://demo-guide", "vehicle://{serial}"],
            "read_only": True,
            "local_only": True,
        },
    }


@app.get("/api/vehicles", tags=["Vehicles"])
def search_vehicles(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Search the local synthetic dataset by serial, make, or model."""
    matches = search_vehicle_summaries(q, limit)
    return {"count": len(matches), "limit": limit, "vehicles": matches}


@app.get("/api/vehicles/{serial}", tags=["Vehicles"])
def get_vehicle(serial: str) -> dict[str, Any]:
    """Return one vehicle record, or 404 for an unknown serial."""
    vehicle = find_vehicle(serial)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="No synthetic vehicle record found.")
    return vehicle


@app.patch("/api/vehicles/{serial}/mileage", tags=["Vehicles"])
def update_manual_mileage(serial: str, payload: ManualMileageUpdate) -> dict[str, Any]:
    """Replace missing current mileage in a synthetic record with advisor-confirmed data."""
    if payload.mileage_date > date.today():
        raise HTTPException(status_code=422, detail="Mileage date cannot be in the future.")
    try:
        vehicle = update_vehicle_mileage(
            serial,
            payload.mileage,
            payload.mileage_date.isoformat(),
            payload.mileage_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not save the synthetic mileage update.") from exc

    if vehicle is None:
        raise HTTPException(status_code=404, detail="No synthetic vehicle record found.")
    return vehicle

# MCP endpoint: http://127.0.0.1:8000/mcp
app.mount("/mcp", mcp_http_app)
