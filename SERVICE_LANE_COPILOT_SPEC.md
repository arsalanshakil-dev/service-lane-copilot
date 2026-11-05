# Service Lane Copilot — MVP Spec

## Purpose

Help a dealership service advisor prepare for a vehicle visit by retrieving its service record from a serial-number lookup, showing service items that are due or coming up with evidence, and preparing customer-facing drafts for advisor review.

This MVP uses synthetic vehicles, service histories, and clearly labeled example maintenance rules. It is a workflow demonstration, not a source of real-world maintenance advice.

## Implementation stack

- **Frontend:** Next.js App Router with React and TypeScript in `frontend/`.
- **Backend:** Python FastAPI REST API plus a standard MCP server in `backend/`.
- **Backend docs:** Swagger UI at `/docs`, OpenAPI JSON at `/openapi.json`, and interface summary at `/api/capabilities`.
- **Runtime database:** Supabase Postgres, accessed only by the Python backend. `data/vehicles.json` is the checked-in synthetic seed fixture, not a runtime fallback.
- **Synthetic seed:** 250 synthetic vehicle records can be loaded with the idempotent backend seed command.
- **Manual mileage:** advisor-reviewed `PATCH /api/vehicles/{serial}/mileage` replaces the current value in the synthetic record stored in Supabase. **Completed services:** advisor-reviewed `POST /api/vehicles/{serial}/services` records a completed service (history event, optional Completed status on a stored recommendation, and a higher odometer reading). These are the only two REST write routes, and MCP remains read-only.
- **API connection:** Next.js rewrites `/api/copilot/*` to the local FastAPI service, avoiding a separate browser CORS configuration for the demo. In development, allow both `localhost` and `127.0.0.1` so Next.js client assets and HMR work from either loopback address. Set the rewrite proxy timeout (`experimental.proxyTimeout`) to 1,800,000 ms so local Ollama requests are not cut off by the 30-second default.
- **Agent connection:** MCP Streamable HTTP at `/mcp` and stdio for local subprocess-based agent harnesses.
- **Local runtime:** Node.js 20.9+ and Python 3.11+.

## MCP interface

Expose the synthetic records to any MCP-compatible agent harness through standard MCP transports. The MCP tools and resources share the Supabase-backed vehicle store with REST. MCP remains read-only; the REST API has two advisor-reviewed synthetic write routes (mileage replacement and completed-service recording).

- Tools: search records, get one vehicle record, prepare customer drafts, prepare record-intake/outside-history drafts, and summarize the dataset.
- Resources: a demo safety guide and individual synthetic vehicle records.
- Draft tools return text only. They cannot send messages, submit requests, update records, book appointments, access a physical vehicle, or reach an external service.
- The HTTP endpoint binds to localhost for the demo. Remote access requires a separately reviewed authentication and deployment setup; do not publicly expose this endpoint as-is.

## Planned vehicle data source: OBD-II/CAN

For a later dealership pilot, add an optional read-only vehicle connection through an OBD-II adapter using CAN where the vehicle supports it. Read the VIN when available, then use an approved VIN decoder/catalog to resolve make, model, and year. Prefill an odometer reading only when the vehicle and adapter expose a supported value, then match the vehicle to dealership history.

- Treat the VIN read from the vehicle as the vehicle identifier; confirm how it maps to the dealership’s “serial number” field before using it as the record lookup key.
- Read only fields the vehicle and adapter actually expose. VIN retrieval and odometer retrieval have different support; do not assume every vehicle provides odometer over generic OBD-II. Some fields may need an approved manufacturer-specific method or may be unavailable.
- OBD-II vehicle data does not replace dealership service history. Keep service events sourced from dealership records or another approved history source.
- Keep each value’s source, retrieval time, units, and availability status. If the OBD reading is missing, stale, or conflicts with the dealership record, show the discrepancy and pause mileage-based recommendations until the advisor resolves it.
- Allow only approved read requests. Do not send coding, configuration, reset, actuation, or other write/control commands to the vehicle.
- The current synthetic demo has no OBD adapter connection and does not read a physical vehicle.

## User and problem

- **Primary user:** dealership service advisor.
- **Current task:** identify the vehicle, review prior service, work out what maintenance may be due next, and explain the recommendation to the customer.
- **Intended benefit:** faster preparation and more recommendations supported by visible service-history evidence.
- **Success measurement:** record a baseline for preparation time and evidence completeness before setting a numeric target.

## MVP workflow

1. Advisor enters a vehicle serial number on an intuitive web page.
2. The app searches the synthetic dealership service-record dataset.
3. For a match in the demo, the app displays synthetic vehicle details, recorded mileage, service history, and data timing. A later connected version may prefill vehicle identity and available odometer data from an OBD-II/CAN adapter.
4. The Python API returns the selected vehicle’s structured, synthetic recommendation examples from the Supabase record, including status, demo rule text, and record evidence. The app does not calculate real service intervals.
5. The app flags safety-related items distinctly and tells the advisor to verify them against an approved source.
6. The app can prepare editable drafts of a customer explanation, quote, and follow-up message. Drafts are never sent or booked automatically.
7. If there is no match or the record is incomplete, the app explains what is missing and offers two paths:
   - prepare a draft to add/register the vehicle in the dealership’s service records;
   - prepare a draft request for another dealership to provide service history.
8. The advisor reviews and handles either draft. The MVP does not contact other dealerships or write to a live dealership system.

## Requirements

### App identity

- The browser tab displays a recognizable Service Lane Copilot icon using the Next.js App Router icon convention.

### Interface quality (issue #32)

- Body text, labels, and controls use at least 11 px text; most reading text is 12–14 px.
- Light and dark themes cover every surface, including cards, inputs, drafts, recommendations, history, forms, telemetry, AI suggestions, and chat.
- At 375 px width the page has no horizontal scroll. The icon sidebar is hidden below 760 px; navigation stays in the top bar.
- Interactive controls show a visible keyboard focus ring and have tap targets of roughly 28 px or more. Controls that do nothing in the demo are not shown as interactive (no dropdown chevron on the dealer card; "?" links to the demo note).
- Service-history rows show the date on one line and the detail under the service name; the draft editor uses the app font.

### Local development origin

- The interactive page must work when opened at either `http://localhost:3000` or `http://127.0.0.1:3000`.
- Next.js development assets and HMR must load from both loopback hostnames; a 403 must not leave a server-rendered but non-interactive page.

### Vehicle record and lookup

- A serial-number lookup returns either one matching synthetic vehicle or a clear no-match result.
- Synthetic vehicle records include serial number, make/model/year, recorded odometer mileage and timestamp, service events, and any missing-data indicators.
- No match, missing mileage, conflicting mileage, or sparse history must be shown as a data limitation; the app must not silently fill gaps.

### Supabase vehicle database

- Supabase Postgres is the runtime source of truth for vehicle records. The backend accesses it through the official Python SDK; the browser and MCP clients never receive database credentials.
- `public.vehicle_records` stores one record per normalized serial number, with the existing structured vehicle object in a JSONB column and an `updated_at` timestamp. The JSON fixture is used only by the seed command.
- Checked-in migrations enable RLS and grant no direct access to `PUBLIC`, `anon`, or `authenticated`; only the backend server key has table access.
- Configure `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in the ignored `backend/.env`. The same config supports hosted Supabase or the local Supabase stack. Never place the key in frontend code or Git.
- Missing configuration, network errors, or migration errors produce a clear unavailable response. The backend never falls back to JSON at runtime.
- The local API and MCP endpoint remain bound to localhost. Hosted-project provisioning, secret entry, and migration execution against a hosted project require an explicit separate action.
- See `docs/feature-spec-supabase-database.md`.

### Manual mileage updates

- An advisor can replace the current mileage for any known synthetic vehicle, whether the existing value is missing or needs correction.
- Record the reading date and source (`advisor_observed` or `customer_reported`); the replacement supersedes the current mileage and does not retain the previous value.
- A reading below recorded service mileage is marked conflicting. Missing, stale, or incomplete service history keeps recommendations paused; mileage entry alone never creates a recommendation or interval.
- This write is available only through the local REST endpoint. MCP tools and resources remain read-only.
- See `docs/feature-spec-manual-mileage.md`.

### Recommendations

- Recommendation examples and due/coming-up labels are explicit structured data in the synthetic JSON records, not a language model’s guess.
- Each result includes service item, status, mileage or history evidence, applicable demo rule, and a plain-language explanation.
- If the available data cannot support a recommendation, show that evidence is insufficient instead of inventing a service item or interval.
- Safety-related items receive a prominent verification label and are not presented as a diagnosis or confirmed defect.
- The interface labels the schedule and records as synthetic demonstration data.

### In-app Ollama agent

- The web app includes a chat assistant that can use every tool and resource registered by the existing MCP server, including fixed resources and resource templates.
- The chat model is selected from models installed on the local Ollama service. Model discovery and inference use only `http://127.0.0.1:11434`; no cloud fallback or remote model URL is allowed.
- Filter embedding-only Ollama models from the chat selector; default to an installed chat-capable model so an embedding model is not sent to `/api/chat`.
- Allow up to 600 seconds per local Ollama HTTP request by default, configurable with backend-only `OLLAMA_TIMEOUT_SECONDS` (30–1800 seconds). This limit applies per request in a multi-step MCP turn.
- Send `think: false` on local chat requests so thinking-capable models do not spend the request timeout on hidden reasoning.
- Return HTTP 503 when local Ollama cannot be reached and HTTP 504 with a timeout message when a running model exceeds the request timeout. Chat failures must never surface as a generic HTTP 500.
- If the backend returns a non-JSON or error response, show a readable error with its HTTP status instead of a JSON parsing exception.
- The assistant may retrieve synthetic data and prepare drafts through existing MCP capabilities. It cannot write records, send messages, submit requests, book appointments, control a vehicle, or access an outside system.
- Vehicle facts, recommendation evidence, and safety status must be grounded in MCP tool/resource output. Incomplete or conflicting data remains uncertain. The model cannot decide maintenance intervals.
- Conversation history is kept in browser memory only.
- **Topic guardrail:** the chat answers dealership service-lane questions only (vehicle lookup, service history, mileage, stored recommendations and evidence, drafts, the synthetic dataset, and how the app works). General Q&A (general knowledge, coding, math, news, weather, personal advice, unrelated writing, or prompt-override requests) receives a fixed refusal explaining what the assistant can help with; the model's own off-topic text is never shown.
- See `docs/feature-spec-local-ollama-chat.md`.

### Local AI drafts and AI-suggested service items

- The Customer drafts panel keeps the instant template draft and offers **Generate with local AI**, which replaces the active draft with local-Ollama-written text that is editable and never sent.
- **Suggest more with local AI** shows up to three model-suggested service items in a separate section labelled "AI suggestion — unverified". They never change stored recommendations.
- Each AI suggestion must cite recorded service-history entries; the backend builds its evidence from those entries and drops suggestions with invalid citations, prices, or duplicates of stored recommendations. Safety-related suggestions are verification prompts only.
- **Mileage-based AI suggestions (issue #30):** the prompt includes current mileage and miles since each recorded service. The model may give its own estimate of a typical interval in miles; it is shown as "Model estimate … Unverified; check the manufacturer schedule." (approved AGENTS.md exception). The backend drops a suggestion that matches a recorded service done fewer miles ago than the model's interval or the 1,000 mi demo floor, or within 30 days when that service's odometer was not recorded. An item never recorded is dropped until the vehicle reaches the model's interval estimate. A service recorded 10 miles ago is never suggested again.
- Records with missing mileage, incomplete or conflicting data, or no history return no AI suggestions and a limitation.
- See `docs/feature-spec-local-ai-assist.md`.

### Recording completed services

- When a service is done, the advisor records it with **✓ Mark as done** on a stored recommendation or **+ Record service** in Service history (service name, date not in the future, optional odometer, optional note).
- `POST /api/vehicles/{serial}/services` saves it to the Supabase record: a newest-first history event marked `advisor_recorded`, the matching recommendation set to **Completed** with completion evidence, and current mileage raised only when the service odometer is higher.
- No next-due interval is calculated; MCP and chat stay read-only. Unknown serial → 404; invalid input or an unknown recommendation → 422 with no write.
- See `docs/feature-spec-record-service.md`.

### Drafts and approvals

- Customer explanations, quote text, follow-ups, vehicle-registration requests, and external-history requests are drafts only.
- An advisor can edit or discard each draft.
- No message sending, appointment booking, payment, repair authorization, or external dealership lookup occurs in the MVP.

## Safety, privacy, and trust boundaries

- Use synthetic data only; do not include client or customer data, secrets, or production credentials. Supabase URL/key settings remain backend-side; never commit or expose the server key.
- Do not claim that a repair is necessary or that a safety defect has been diagnosed.
- Show the evidence and rule behind every suggested service so the advisor can check it.
- Treat missing, stale, or contradictory records as uncertainty that requires advisor follow-up.
- Keep all customer-facing or external actions behind advisor review.
- The in-app assistant uses only local Ollama inference and the project's own MCP server. No chat message is sent to a hosted model or external service.

## Out of scope

- Connecting to a dealer management system, manufacturer service database, vehicle-history provider, or another dealership.
- Reading a physical vehicle through an OBD-II/CAN adapter or sending commands to a vehicle ECU.
- Looking up real vehicles from their serial number.
- Sending messages, submitting registration changes, creating quotes in a live system, booking appointments, or authorizing repairs.
- Using a generative model to decide which maintenance is due.
- Provisioning/writing to a hosted Supabase project, production dealership data, public API deployment, or claims that demo rules are valid for any real make/model/year.

## Verification plan

Before calling the MVP ready, automate these behaviors where practical and record the exact command and result. Safety, data-integrity, API-contract, and MCP side-effect checks must not be waived silently:

1. Known serial number returns the matching synthetic vehicle and history only.
2. Unknown serial number returns no fabricated vehicle or history and offers the two draft paths.
3. Due and coming-up examples match the configured demo rules and cite the triggering mileage/history evidence.
4. Missing or conflicting mileage/history produces an uncertainty state, not a confident recommendation.
5. Safety-tagged items display the verification warning.
6. Drafts are editable and no send, booking, or external-lookup action is available.
7. Explanations and quotes do not add facts absent from the vehicle record or configured demo rules.
8. MCP tool/resource discovery works over stdio and Streamable HTTP; unknown serials return an explicit no-record result.
9. MCP draft tools return unsent drafts and expose no side-effecting operation.
10. The chat discovers and calls all registered MCP tools and can read fixed and templated MCP resources.
11. The in-app assistant sends inference only to the local Ollama service and has no hosted-model fallback.
12. Multi-step search/retrieve/draft tasks use MCP results; unknown or incomplete records remain explicit and uncertain.
13. Ollama unavailable, no installed model, invalid tool, and MCP tool failure produce clear errors without making external calls.
14. Chat cannot send drafts, write a vehicle record, book service, or control a vehicle; history is not persisted server-side.
15. Manual mileage can replace the current value with date and source for a known serial; invalid/future values are rejected, unknown serials return 404, and conflicting/incomplete evidence keeps recommendations paused.
16. Supabase migrations create the private record table with RLS/privileges; idempotent seeding loads 250 synthetic records; API/MCP reads use the database, and mileage replacement persists while preserving unrelated record fields.
17. Missing Supabase configuration or provider failure returns unavailable without JSON fallback; frontend and MCP callers cannot read or expose database keys.

Review the code changes and evidence for each check before accepting them. A check that was not run is **unverified**, not passed. The existing verification plan defines expected behavior; it is not evidence that implementation has already passed.

## Spec-driven change workflow

Every implementation change must follow this order:

1. Read `AGENTS.md`, `MEMORY.md`, and this spec. Inspect the current code and relevant data contracts before editing.
2. Write or update the requirement first. For changes to current behavior, update this spec; for a distinct feature, create a feature spec from `docs/feature-spec-template.md` and link it here.
3. State the user/problem, in-scope and out-of-scope behavior, data sources, failure cases, safety boundaries, and observable acceptance criteria. Turn acceptance criteria into repeatable tests or a named manual review where automation is not practical.
4. Break the approved requirement into small tasks and implement one task at a time. Do not add unrequested behavior, new data sources, dependencies, or side effects.
5. Run the checks named by the spec, inspect the full diff, and update `MEMORY.md` with verified changes and remaining gaps.
6. Report what changed, which checks passed or were not run, and any unresolved decision. Never state that a behavior is verified unless its check was run successfully.

### Definition of done

- The implementation matches an explicit spec and acceptance criteria.
- Synthetic-data, no-fabrication, evidence-display, uncertainty, and human-approval boundaries remain intact.
- Relevant automated checks pass; unrun checks and environment blockers are stated plainly.
- Dependency changes are justified, pinned, and recorded in the appropriate lock file when the package manager is available.
- No unrelated files or behaviors are changed.
- The spec, memory, setup instructions, and implementation agree.

## Decisions and tasks to finalize the MVP spec

Items below are split between the synthetic-data MVP and a later dealership pilot. Suggested defaults are proposals, not approved requirements.

### Needed for the synthetic-data MVP

- [x] **Define the demo maintenance rules.** Use fictional example mileage thresholds and label them as synthetic. They demonstrate due, coming-up, and not-yet-due results; they are not approved guidance.
- [x] **Define sample record coverage.** Use 250 synthetic vehicles: 10 hand-authored examples plus 240 deterministic generated records. Cover complete history, no matching recommendation, missing mileage, stale mileage, conflicting mileage, and unknown serial numbers.
- [x] **Set the draft content contract.** Explanation, quote, follow-up, dealership-record intake, and outside-history drafts are editable and unsent. Quote drafts contain suggested line items but no invented pricing.
- [x] **Set MVP acceptance checks.** The nine repeatable behavior checks are listed in the verification plan. Their execution is still needed before claiming the checks passed.
- [x] **Choose implementation stack and local run instructions.** Use a Python FastAPI backend and a React/Next.js App Router frontend with TypeScript. Expose read-only MCP tools over Streamable HTTP and stdio. Run the two local development servers using the root README instructions.

**Demo release scope:** approved as a synthetic-data demonstration. It is a local, non-production prototype with a Python REST backend whose only write operations are the advisor-reviewed synthetic mileage update and completed-service recording, a read-only MCP server, and a Next.js frontend. It has no external integrations, real customer data, or live dealership actions. The dataset contains 250 records total; generated profiles use fictional makes/models and repeatable example scenarios.

### Needed before a real dealership pilot

- [ ] **Choose the approved maintenance source.** Identify the authoritative schedule for each supported vehicle and the dealership owner responsible for approving updates. No real recommendation should use demo rules.
- [ ] **Choose the vehicle-history source and access path.** Confirm whether the dealership has an API/export or approved provider, what fields it returns, and how outside-dealership history can be requested. Keep that request as an advisor-reviewed draft unless a permitted integration is later approved.
- [ ] **Plan OBD-II/CAN support.** Select an adapter, supported vehicle/protocol coverage, approved read-only identifiers and mileage fields, VIN decoder/catalog, VIN-to-dealership-serial matching rules, and safe failure behavior. Pilot with representative vehicles before relying on any field.
- [ ] **Define data handling.** Confirm allowed customer/vehicle data, user sign-in and roles, retention/deletion, audit history, and the environment where records may be stored. Use mock data until these are decided.
- [ ] **Define quote boundaries.** Identify the approved labor/parts pricing source and whether generated quotes are estimates or only editable line-item drafts. No price should be invented.
- [ ] **Set pilot measures.** Capture current advisor preparation time and a baseline for recommendations with traceable evidence; then set numeric targets with the dealership.
- [ ] **Plan advisor review and rollout.** Name reviewers for safety flags, recommendation wording, draft quality, and escalation paths when data is missing or contradictory.

### Decisions already captured

- Primary user is a dealership service advisor; the interface is a web page.
- MCP-compatible agent harnesses can access the same synthetic records through read-only tools/resources over stdio or local Streamable HTTP.
- The released demo uses 250 synthetic vehicle records and fictional service histories/rules.
- Demo lookup uses a synthetic vehicle serial. A connected version may read a VIN through OBD-II/CAN and must map it to the dealership’s vehicle identifier before matching. A missing record offers a dealership-record intake draft or an outside-history request draft.
- A future connected workflow may prefill vehicle identity and available mileage from OBD-II/CAN; the current demo has no physical adapter integration. Service history remains a separate source.
- Recommendations show service item, due/coming-up status, mileage or history evidence, and a customer-friendly explanation.
- Safety-related items are flagged for advisor verification.
- Customer explanations, quote text, follow-ups, registration requests, and outside-history requests are drafts only; nothing is sent or submitted.
- Success should include faster preparation and recommendations backed by service history. Numeric targets are deferred until a baseline is measured.

## Project files

- `AGENTS.md` defines the required spec-first process and safety rules for coding agents.
- `.github/workflows/verify.yml` runs the backend regression suite and frontend production build for pull requests and main pushes.
- `MEMORY.md` records verified implementation facts and current gaps; it does not override this spec.
- `docs/feature-spec-template.md` is the template for distinct features.
- `docs/feature-spec-local-ollama-chat.md` defines the in-app assistant, local-only Ollama boundary, and full MCP capability access.
- `docs/feature-spec-manual-mileage.md` defines advisor mileage replacement, provenance, and evidence limits.
- `docs/feature-spec-supabase-database.md` defines the runtime Supabase store, local/hosted configuration, seed path, and security boundaries.
- `frontend/app/` contains the Next.js page and styles.
- `frontend/app/icon.svg` is the browser-tab favicon.
- `frontend/next.config.ts` proxies browser API calls to FastAPI.
- `backend/app/main.py` implements the REST API and mounts the MCP HTTP endpoint.
- `backend/app/mcp_server.py` defines MCP tools/resources and the stdio entry point.
- `backend/app/local_agent.py` discovers local Ollama models and runs a bounded tool loop through the MCP server.
- `frontend/app/chat-panel.tsx` provides the advisor-facing local agent chat.
- `backend/mcp_stdio.py` is the local stdio launcher for MCP hosts.
- `backend/app/data_store.py` loads and updates vehicle records from Supabase.
- `backend/seed_supabase.py` loads the synthetic JSON fixture into Supabase; it is not used for runtime reads.
- `supabase/migrations/` tracks the database schema and access controls.
- `backend/requirements.txt` pins Python and MCP dependencies.
- `data/vehicles.json` stores the 250 vehicle records separately from the interface and API code.
- `README.md` explains setup, local run commands, and sample vehicle scenarios.

