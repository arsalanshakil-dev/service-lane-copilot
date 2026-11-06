# Service Lane Copilot — Project Context

## What this project is

Service Lane Copilot is a local demonstration app for dealership service advisors. It helps an advisor look up a vehicle in a synthetic dealership service-history dataset, review evidence-backed demo service items, and prepare editable customer or record-request drafts.

The demo uses 1,000 fictional vehicle records. It is not a production maintenance system and does not provide real vehicle advice. Recommendations are computed from editable demo maintenance rules (miles since the last recorded service) and the vehicle's recorded history and mileage, or entered by an advisor; they never come from a language model's judgment. Separately, the advisor can ask the local Ollama model for up to three extra "AI suggestion — unverified" items based on the current mileage. These are shown apart from the stored recommendations and must cite recorded service history. They may show the model's own unverified mileage-interval estimate. The backend removes prices, duplicates, and anything done too recently or not due yet by mileage.

## How it is built

- **Frontend:** Next.js App Router, React, and TypeScript in `frontend/`.
- **Backend:** Python, FastAPI, and MCP in `backend/`.
- **Database:** Supabase Postgres is the runtime source shared by REST and MCP. `data/vehicles.json` is the 1,000-record synthetic seed fixture only; `backend/generate_synthetic_vehicles.py` regenerates the generated part repeatably.
- **REST overview:** FastAPI Swagger UI is at `/docs`; OpenAPI JSON is at `/openapi.json`.
- **Agent access:** MCP is available over local Streamable HTTP and stdio. The web app also includes a chat assistant that uses the same MCP tools/resources through Ollama at `127.0.0.1:11434` only.

## Main advisor workflow

1. Enter a vehicle serial number in the web app, or open **Vehicle records** to browse (choosing how many rows per page) and search all records and select one. Each record has an **✦ AI summary** with an exact "Needs now" list from the stored record plus short, unverified local-AI context.
2. Review the matching synthetic vehicle (Overview, History, Telemetry, and Change log tabs), mileage, history, data timing, limitations, and a separately labeled simulated 5-minute telemetry recording that can be scrolled and zoomed.
3. Review explicitly stored due or coming-up examples with their record evidence and demo rule.
4. Add a new vehicle from **Vehicle records** (or from a not-found lookup), and correct records in place: **Edit details**, edit service-history entries (history is never deleted), and add, edit, or remove recommendations (marked Advisor-entered). Every save is listed in the record's **Change log**. The chat can propose the same changes; they are saved only after you click **Apply change**.
   If current mileage is missing or needs correction, replace it with an advisor-confirmed reading, date, and source in the local synthetic record; mileage alone does not resolve missing history.
   When a service is done (for example an oil change), use **✓ Mark as done** on its recommendation or **+ Record service** in Service history. The service is saved to the vehicle record in Supabase, the recommendation shows Completed, and a higher odometer reading updates current mileage.
5. Prepare and edit customer explanations, quote text, follow-ups, or record/history request drafts. Template drafts appear instantly; **Generate with local AI** rewrites the active draft with a local Ollama model (no prices; never sent).
6. Optionally request **AI suggestions** for extra items to check. Records with missing mileage, incomplete or conflicting data, or no history get a limitation message instead.
7. The advisor can use the same lookup, evidence, and draft capabilities through the in-app local assistant. The AI model for every AI feature, the theme (Light, Dark, System), and the time zone used to show times are chosen in **Settings** (the ··· menu beside the advisor name; ⚙ in the top bar on phones). Settings also holds the editable **maintenance rules** (shared by everyone) from which Due / Coming up recommendations are computed. The assistant answers dealership service questions only; general Q&A gets a fixed refusal.
8. The advisor decides what to do with each draft; the app does not send or submit it.

No match or incomplete, stale, or contradictory data must remain visible as uncertainty. The app must not fill gaps or present an unsupported service as necessary. Safety-related items are prompts for advisor verification, not diagnoses.

## Boundaries

- Use synthetic data only. Never add real customer, vehicle, or dealership records, credentials, or secrets.
- Drafts are text only: they do not send messages, submit requests, book appointments, modify records, or contact external services. A separate local REST endpoint lets an advisor replace synthetic current mileage with date/source provenance.
- MCP read and draft tools never change records. MCP write tools (issue #44) add and edit synthetic records with the same validation and change log as the app; the in-app chat only proposes them for advisor confirmation. Chat uses installed local Ollama models, and chat history is not stored by the backend.
- Supabase is configured for either local development or a user-provided hosted project. The Python backend alone connects to it; no hosted project is provisioned by this code change. `SUPABASE_URL` and `SUPABASE_SECRET_KEY` stay in `backend/.env`.
- OBD-II/CAN, live dealership systems, external history providers, real maintenance schedules, and production deployment are out of scope for this demo. Future OBD-II work must be separately specified and read-only.
- Do not invent prices, vehicle details, maintenance intervals, or history.

## Which document governs what

- [`docs/guide/TESTER_GUIDE.md`](docs/guide/TESTER_GUIDE.md) is the guide to give testers: a short explanation, a one-command install (`scripts/install-windows.ps1`, `scripts/install.sh`), a five-minute demo script, and a test checklist.
- [`SERVICE_LANE_COPILOT_SPEC.md`](SERVICE_LANE_COPILOT_SPEC.md) is the **authoritative product requirements and acceptance criteria**. Change it first when product behavior or scope changes. Feature specs in `docs/` (for example [`docs/spec/feature-spec-local-ai-assist.md`](docs/spec/feature-spec-local-ai-assist.md)) hold the detailed rules for individual features.
- [`AGENTS.md`](AGENTS.md) defines the coding workflow and safety rules, including keeping the spec, `MEMORY.md`, and this file current with every new requirement and change. [`CLAUDE.md`](CLAUDE.md) imports it so Claude Code follows the same rules.
- [`MEMORY.md`](MEMORY.md) is a short, verified implementation status and known-gaps summary. It is not a requirements source.
- `CONTEXT.md` is an onboarding map only. It summarizes the project and links to the controlling documents; it must not create or override requirements.

Before changing code, read the spec and memory, inspect the relevant implementation and data, and follow the spec-driven workflow in `AGENTS.md`. Treat unrun checks as unverified.
