# Project memory

Last updated: 2026-11-04

This file is a continuity summary, not a requirements document. Product requirements live in `SERVICE_LANE_COPILOT_SPEC.md`; development rules live in `AGENTS.md`.

## Project purpose and current scope

- Service Lane Copilot is a local synthetic-data demo for a dealership service advisor.
- The frontend is Next.js App Router, React, and TypeScript in `frontend/`.
- The backend is Python FastAPI plus MCP in `backend/`.
- `data/vehicles.json` contains 250 synthetic records. It is the source for both REST and MCP access.
- All vehicle records, recommendations, mileage, rules, and prices are demo content. No real dealership or customer information is allowed.
- Due/coming-up items are stored synthetic examples, not calculated real maintenance guidance.

## Architecture facts

- REST endpoints: `GET /api/health`, `GET /api/vehicles`, `GET /api/vehicles/{serial}`, and `PATCH /api/vehicles/{serial}/mileage` for replacing missing current mileage in a known synthetic record.
- Swagger UI: `/docs`; OpenAPI JSON: `/openapi.json`; REST/MCP interface summary: `/api/capabilities`.
- MCP Streamable HTTP endpoint: `http://127.0.0.1:8000/mcp`, mounted in `backend/app/main.py`.
- MCP stdio launcher: `backend/mcp_stdio.py`.
- MCP tools: `search_vehicle_records`, `get_vehicle_record`, `create_customer_draft`, `create_record_request_draft`, and `dataset_summary`.
- MCP resources: `service-lane://demo-guide` and `vehicle://{serial}`.
- MCP tools remain read-only. Draft tools return text with `sent: false` / `submitted: false`; they do not contact anyone or change records. Only the local REST mileage route writes the synthetic JSON file.
- Next.js proxies `/api/copilot/*` to FastAPI using `frontend/next.config.ts`.
- Manual mileage entry replaces the current value and records an ISO date plus source (`advisor_observed` or `customer_reported`). Prior current readings are not retained.
- A manual reading below a mileage recorded in service history is marked conflicting. Missing history mileage remains missing, so recommendations stay paused when evidence is insufficient.
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
- For the manual mileage change, the local command runner did not start, so backend and frontend checks were not run. Treat runtime behavior as unverified until checks run in a configured environment.
- The acceptance and verification plan is in `SERVICE_LANE_COPILOT_SPEC.md` and `docs/feature-spec-manual-mileage.md`. No manual mileage checks have yet been run.
- Do not assume the MCP mount, tools, UI, or API are runtime-verified based on source inspection alone.
- No live OBD-II/CAN integration, dealership history integration, authentication, hosted deployment, or real maintenance catalog exists.
- Numeric success targets are open until advisor baseline measures are captured.

## Update rule

After a task, update this file only with facts confirmed from code, commands, or user decisions. Record unresolved items as open; never turn a proposed default into an approved requirement without user direction.
