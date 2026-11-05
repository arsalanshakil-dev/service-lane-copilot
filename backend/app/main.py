"""REST API and local MCP HTTP mount for the synthetic Service Lane Copilot."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from .data_store import (
    VehicleStoreUnavailableError,
    find_vehicle,
    load_vehicles,
    list_vehicle_summaries,
    UnknownRecommendationError,
    record_completed_service,
    update_vehicle_mileage,
)
from .mcp_server import mcp_server, mcp_http_app
from .ai_assist import generate_ai_draft, generate_ai_suggestions
from .local_agent import (
    OllamaRequestError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    chat_with_local_agent,
    list_local_models,
)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4_000)


class LocalChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4_000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class AiDraftRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    draft_type: Literal["explanation", "quote", "followup"] = Field(alias="draftType")


class AiSuggestionsRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


class ManualMileageUpdate(BaseModel):
    """Advisor-confirmed manual odometer reading for a synthetic record."""

    mileage: int = Field(ge=0)
    mileage_date: date = Field(alias="mileageDate")
    mileage_source: Literal["advisor_observed", "customer_reported"] = Field(alias="mileageSource")


class CompletedServiceRecord(BaseModel):
    """Advisor-confirmed completed service for a synthetic record (issue #28)."""

    service_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = Field(
        alias="serviceName"
    )
    service_date: date = Field(alias="serviceDate")
    mileage: int | None = Field(default=None, ge=0)
    detail: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    recommendation_name: str | None = Field(default=None, alias="recommendationName", max_length=120)


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
        "REST API and local Ollama chat over Supabase-backed synthetic vehicle records. The 250-record JSON file is a seed fixture only.\n\n"
        "## REST API and local chat\n"
        "Vehicle search and retrieval use synthetic records. The app chat uses only local Ollama at 127.0.0.1:11434 and the registered MCP tools/resources. "
        "Unknown serials return 404; no real dealership data is queried.\n\n"
        "## MCP agent access\n"
        "The same dataset is available to MCP-compatible agents over Streamable HTTP at `/mcp` "
        "or through the local stdio launcher. MCP draft tools never send or submit content. "
        "The MCP protocol endpoint is not an OpenAPI route; see `/api/capabilities` for its tools and resources.\n\n"
        "All vehicle, mileage, history, and recommendation content is synthetic demo data. Supabase credentials are required on the backend; the API never falls back to JSON at runtime."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "Backend overview",
            "description": "Service status and a summary of the REST, local chat, and MCP interfaces.",
        },
        {
            "name": "Vehicles",
            "description": "Search and retrieval over synthetic records plus an advisor-reviewed local mileage update.",
        },
    ],
    lifespan=lifespan,
)


@app.exception_handler(VehicleStoreUnavailableError)
async def vehicle_store_unavailable(_: Request, __: VehicleStoreUnavailableError) -> JSONResponse:
    """Hide provider details and return a safe database-unavailable response."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Vehicle database unavailable. Check Supabase setup and try again."},
    )


@app.get("/api/health", tags=["Backend overview"])
def health() -> dict[str, Any]:
    """Return service status and Supabase-backed synthetic record count."""
    return {
        "status": "ok",
        "database": "supabase",
        "synthetic_data": True,
        "record_count": len(load_vehicles()),
    }


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
        "database": {
            "provider": "Supabase Postgres",
            "source_of_truth": "vehicle_records",
            "seed_fixture": "data/vehicles.json",
            "runtime_json_fallback": False,
        },
        "rest": {
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/api/health",
            "search_vehicles": "/api/vehicles?q={query}&limit={limit}",
            "get_vehicle": "/api/vehicles/{serial}",
            "vehicle_record_data": ["synthetic identity", "mileage", "service history", "demo recommendations", "simulated OBD telemetry"],
            "update_manual_mileage": "PATCH /api/vehicles/{serial}/mileage",
            "record_completed_service": "POST /api/vehicles/{serial}/services",
            "local_chat_models": "GET /api/chat/models",
            "local_mcp_chat": "POST /api/chat",
            "local_ai_draft": "POST /api/vehicles/{serial}/ai-draft",
            "local_ai_suggestions": "POST /api/vehicles/{serial}/ai-suggestions",
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
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict[str, Any]:
    """List or search synthetic records by serial, make, model, or year, one page at a time.

    `total` is the number of matching records; `count` is the number on this page.
    """
    total, page = list_vehicle_summaries(q, limit, offset)
    return {"count": len(page), "total": total, "limit": limit, "offset": offset, "vehicles": page}


@app.get("/api/vehicles/{serial}", tags=["Vehicles"])
def get_vehicle(serial: str) -> dict[str, Any]:
    """Return one vehicle record, or 404 for an unknown serial."""
    vehicle = find_vehicle(serial)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="No synthetic vehicle record found.")
    return vehicle

@app.get("/api/chat/models", tags=["Backend overview"])
async def chat_models() -> dict[str, Any]:
    """List models already installed in the local Ollama service."""
    try:
        models = await asyncio.to_thread(list_local_models)
    except OllamaTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start the local Ollama app and try again.",
        ) from exc
    except OllamaRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"local_only": True, "models": models}


@app.post("/api/chat", tags=["Backend overview"])
async def local_chat(payload: LocalChatRequest) -> dict[str, Any]:
    """Chat with a local Ollama model using this app's registered MCP tools/resources."""
    try:
        return await chat_with_local_agent(
            payload.model,
            payload.message,
            [turn.model_dump() for turn in payload.history],
        )
    except OllamaTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start the local Ollama app and try again.",
        ) from exc
    except OllamaRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _ollama_http_error(exc: Exception) -> HTTPException:
    """Map a local Ollama failure to the same 504/503/502 responses as the chat route."""
    if isinstance(exc, OllamaTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, OllamaUnavailableError):
        return HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start the local Ollama app and try again.",
        )
    return HTTPException(status_code=502, detail=str(exc))


async def _known_vehicle(serial: str) -> dict[str, Any]:
    vehicle = await asyncio.to_thread(find_vehicle, serial)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="No synthetic vehicle record found.")
    return vehicle


@app.post("/api/vehicles/{serial}/ai-draft", tags=["Vehicles"])
async def ai_customer_draft(serial: str, payload: AiDraftRequest) -> dict[str, Any]:
    """Write an editable customer draft with a local Ollama model. Nothing is sent or stored."""
    vehicle = await _known_vehicle(serial)
    try:
        return await generate_ai_draft(payload.model, vehicle, payload.draft_type)
    except (OllamaUnavailableError, OllamaRequestError) as exc:
        raise _ollama_http_error(exc) from exc


@app.post("/api/vehicles/{serial}/ai-suggestions", tags=["Vehicles"])
async def ai_service_suggestions(serial: str, payload: AiSuggestionsRequest) -> dict[str, Any]:
    """Return up to three validated, unverified AI-suggested service items. Nothing is stored."""
    vehicle = await _known_vehicle(serial)
    try:
        return await generate_ai_suggestions(payload.model, vehicle)
    except (OllamaUnavailableError, OllamaRequestError) as exc:
        raise _ollama_http_error(exc) from exc


@app.patch("/api/vehicles/{serial}/mileage", tags=["Vehicles"])
def update_manual_mileage(serial: str, payload: ManualMileageUpdate) -> dict[str, Any]:
    """Replace current mileage in a synthetic record with advisor-confirmed data."""
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


@app.post("/api/vehicles/{serial}/services", tags=["Vehicles"])
def record_service(serial: str, payload: CompletedServiceRecord) -> dict[str, Any]:
    """Record an advisor-completed service in a synthetic record and save it to Supabase.

    Adds a service-history event, optionally marks one stored recommendation Completed,
    and raises current mileage when the service odometer is higher. No interval is calculated.
    """
    if payload.service_date > date.today():
        raise HTTPException(status_code=422, detail="Service date cannot be in the future.")
    try:
        vehicle = record_completed_service(
            serial,
            payload.service_name,
            payload.service_date.isoformat(),
            payload.mileage,
            payload.detail,
            payload.recommendation_name,
        )
    except UnknownRecommendationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if vehicle is None:
        raise HTTPException(status_code=404, detail="No synthetic vehicle record found.")
    return vehicle

# MCP endpoint: http://127.0.0.1:8000/mcp
app.mount("/mcp", mcp_http_app)
