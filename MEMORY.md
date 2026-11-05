# Project memory

Last updated: 2026-11-05

This file is a continuity summary, not a requirements document. Product requirements live in `SERVICE_LANE_COPILOT_SPEC.md`; development rules live in `AGENTS.md`.

## Project purpose and current scope

- Service Lane Copilot is a local synthetic-data demo for a dealership service advisor.
- The frontend is Next.js App Router, React, and TypeScript in `frontend/`.
- The backend is Python FastAPI plus MCP in `backend/`.
- `data/vehicles.json` contains 250 synthetic records. It is the source for both REST and MCP access.
- All vehicle records, recommendations, mileage, rules, and prices are demo content. No real dealership or customer information is allowed.
- Due/coming-up items are stored synthetic examples, not calculated real maintenance guidance.

## Architecture facts

- REST endpoints: `GET /api/health`, `GET /api/vehicles`, `GET /api/vehicles/{serial}`, `GET /api/chat/models`, and `POST /api/chat`.
- Swagger UI: `/docs`; OpenAPI JSON: `/openapi.json`; REST/MCP interface summary: `/api/capabilities`.
- MCP Streamable HTTP endpoint: `http://127.0.0.1:8000/mcp`, mounted in `backend/app/main.py`.
- MCP stdio launcher: `backend/mcp_stdio.py`.
- MCP tools: `search_vehicle_records`, `get_vehicle_record`, `create_customer_draft`, `create_record_request_draft`, and `dataset_summary`.
- MCP resources: `service-lane://demo-guide` and `vehicle://{serial}`.
- MCP tools are read-only. Draft tools return text with `sent: false` / `submitted: false`; they do not contact anyone or change records.
- Next.js proxies `/api/copilot/*` to FastAPI using `frontend/next.config.ts`.
- In-app chat exposes `GET /api/chat/models` and `POST /api/chat`; model discovery and inference are fixed to Ollama at `http://127.0.0.1:11434` with no cloud fallback.
- `backend/app/local_agent.py` discovers MCP tools and resources in-process with the pinned MCP SDK, passes tool schemas to Ollama, reads advertised resources, and limits each turn to six tool rounds/twelve tool calls. It refuses an answer when the model uses no MCP capability.
- `frontend/app/chat-panel.tsx` keeps chat history in browser state only, offers models reported by local Ollama, and shows MCP capabilities used. Chat is not persisted server-side.
- OBD-II/CAN is future scope. This demo has no physical vehicle connection. VIN may be available through OBD-II; odometer support varies; service history is a separate source.

## Local run commands

Requirements: Node.js 20.9+ and Python 3.11+.

Backend, from `backend/`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`:

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`. For stdio MCP hosts, launch `<backend>/.venv/Scripts/python.exe <backend>/mcp_stdio.py`.

## Verified state and known gaps

- Stack files and setup instructions are present, but the Next.js/FastAPI/MCP runtime has not been launched in this workspace.
- No backend, frontend, or Ollama checks were run for the local chat change. Treat runtime behavior and model tool-calling support as unverified until checked with the local services.
- The acceptance and verification plan is in `SERVICE_LANE_COPILOT_SPEC.md` and `docs/feature-spec-local-ollama-chat.md`. The local agent and chat have not been run in this environment; tool-calling behavior is unverified until exercised with an installed Ollama model.
- Do not assume the MCP mount, tools, UI, or API are runtime-verified based on source inspection alone.
- No live OBD-II/CAN integration, dealership history integration, authentication, hosted deployment, or real maintenance catalog exists.
- Numeric success targets are open until advisor baseline measures are captured.

## Update rule

After a task, update this file only with facts confirmed from code, commands, or user decisions. Record unresolved items as open; never turn a proposed default into an approved requirement without user direction.
