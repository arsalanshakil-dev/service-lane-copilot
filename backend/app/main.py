"""REST API and local MCP HTTP mount for the synthetic Service Lane Copilot."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .data_store import find_vehicle, load_vehicles, search_vehicle_summaries
from .mcp_server import mcp_server, mcp_http_app
from .local_agent import (
    OllamaRequestError,
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
        "Read-only REST API over the 250-record synthetic vehicle dataset.\n\n"
        "## REST API\n"
        "Use the vehicle routes to search and retrieve synthetic vehicle records. "
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
            "description": "Read-only search and retrieval over synthetic vehicle records.",
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
            "local_chat_models": "GET /api/chat/models",
            "local_mcp_chat": "POST /api/chat",
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

@app.get("/api/chat/models", tags=["Backend overview"])
async def chat_models() -> dict[str, Any]:
    """List models already installed in the local Ollama service."""
    try:
        models = await asyncio.to_thread(list_local_models)
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
    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is unavailable. Start the local Ollama app and try again.",
        ) from exc
    except OllamaRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc




# MCP endpoint: http://127.0.0.1:8000/mcp
app.mount("/mcp", mcp_http_app)
