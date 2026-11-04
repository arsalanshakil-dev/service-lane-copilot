# Service Lane Copilot — Project Context

## What this project is

Service Lane Copilot is a local demonstration app for dealership service advisors. It helps an advisor look up a vehicle in a synthetic dealership service-history dataset, review evidence-backed demo service items, and prepare editable customer or record-request drafts.

The demo uses 250 fictional vehicle records. It is not a production maintenance system and does not provide real vehicle advice. Recommendations come from explicit synthetic record data and example rules, not a language model's judgment.

## How it is built

- **Frontend:** Next.js App Router, React, and TypeScript in `frontend/`.
- **Backend:** Python, FastAPI, and MCP in `backend/`.
- **Data:** `data/vehicles.json` is the synthetic dataset shared by REST and MCP.
- **REST overview:** FastAPI Swagger UI is at `/docs`; OpenAPI JSON is at `/openapi.json`.
- **Agent access:** MCP is available over local Streamable HTTP and stdio.

## Main advisor workflow

1. Enter a vehicle serial number in the web app.
2. Review the matching synthetic vehicle, mileage, history, data timing, and limitations.
3. Review explicitly stored due or coming-up examples with their record evidence and demo rule.
4. Prepare and edit customer explanations, quote text, follow-ups, or record/history request drafts.
5. The advisor decides what to do with each draft; the app does not send or submit it.

No match or incomplete, stale, or contradictory data must remain visible as uncertainty. The app must not fill gaps or present an unsupported service as necessary. Safety-related items are prompts for advisor verification, not diagnoses.

## Boundaries

- Use synthetic data only. Never add real customer, vehicle, or dealership records, credentials, or secrets.
- Drafts are text only. Do not send messages, submit requests, book appointments, modify records, or contact external services.
- MCP operations remain read-only apart from returning draft text; they do not persist changes.
- OBD-II/CAN, live dealership systems, external history providers, real maintenance schedules, and production deployment are out of scope for this demo. Future OBD-II work must be separately specified and read-only.
- Do not invent prices, vehicle details, maintenance intervals, or history.

## Which document governs what

- [`SERVICE_LANE_COPILOT_SPEC.md`](SERVICE_LANE_COPILOT_SPEC.md) is the **authoritative product requirements and acceptance criteria**. Change it first when product behavior or scope changes.
- [`AGENTS.md`](AGENTS.md) defines the coding workflow and safety rules.
- [`MEMORY.md`](MEMORY.md) is a short, verified implementation status and known-gaps summary. It is not a requirements source.
- `CONTEXT.md` is an onboarding map only. It summarizes the project and links to the controlling documents; it must not create or override requirements.

Before changing code, read the spec and memory, inspect the relevant implementation and data, and follow the spec-driven workflow in `AGENTS.md`. Treat unrun checks as unverified.
