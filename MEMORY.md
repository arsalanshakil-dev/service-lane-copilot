# Project memory

Last updated: 2026-11-05

This file is a continuity summary, not a requirements document. Product requirements live in `SERVICE_LANE_COPILOT_SPEC.md`; development rules live in `AGENTS.md`.

## Project purpose and current scope

- Service Lane Copilot is a local synthetic-data demo for a dealership service advisor.
- The frontend is Next.js App Router, React, and TypeScript in `frontend/`.
- The backend is Python FastAPI plus MCP in `backend/`.
- Supabase Postgres table `public.vehicle_records` is the runtime source for REST and MCP. `data/vehicles.json` contains 250 synthetic seed records only; there is no runtime JSON fallback.
- Backend configuration is `SUPABASE_URL` plus `SUPABASE_SECRET_KEY` in ignored `backend/.env`; never expose the secret key to frontend code.
- All vehicle records, recommendations, mileage, rules, and prices are demo content. No real dealership or customer information is allowed.
- Due/coming-up items are stored synthetic examples, not calculated real maintenance guidance.

## Architecture facts

- REST endpoints: `GET /api/health`, `GET /api/vehicles`, `GET /api/vehicles/{serial}`, `PATCH /api/vehicles/{serial}/mileage`, `GET /api/chat/models`, `POST /api/chat`, `POST /api/vehicles/{serial}/ai-draft`, and `POST /api/vehicles/{serial}/ai-suggestions`.
- `backend/app/ai_assist.py` (issue #22) makes one `think: false` Ollama call per request. AI drafts reject prices; AI suggestions use a JSON-schema `format`, must cite history entries by number, and are dropped for invalid citations, prices, stated intervals, or duplicates (max 3). Evidence text is built by the backend from cited entries. Records with missing mileage, incomplete/conflicting flags, or no history return a limitation without an Ollama call. Telemetry is excluded from prompts. Nothing is persisted. The page keeps instant template drafts and shows AI suggestions in a separate "Unverified" section. Live check 2026-11-05 with `qwen3.5:4b` on CPU: suggestions for NS-2048 and NS-7316 returned 3 grounded items each (cabin air filter, battery, wipers; 0 dropped) in 64–94 s after the prompt was reworded (the first wording produced empty lists); an explanation draft for NS-2048 returned HTTP 200 in 21 s through the Next proxy. Gap: the model may group an "Advisor verification" item with due/coming-up items in draft wording.
- Next.js's rewrite proxy cut requests off at its 30 s default ("socket hang up" → HTTP 500 in the browser), which also affected the chat panel. `frontend/next.config.ts` sets `experimental.proxyTimeout: 1_800_000`.
- On Windows, uvicorn `--reload` was observed (2026-11-05) to log "Reloading…" after a new module was added but keep serving old code; restart the backend if new routes return FastAPI's generic 404.
- Swagger UI: `/docs`; OpenAPI JSON: `/openapi.json`; REST/MCP interface summary: `/api/capabilities`.
- MCP Streamable HTTP endpoint: `http://127.0.0.1:8000/mcp`, mounted in `backend/app/main.py`.
- MCP stdio launcher: `backend/mcp_stdio.py`.
- MCP tools: `search_vehicle_records`, `get_vehicle_record`, `create_customer_draft`, `create_record_request_draft`, and `dataset_summary`.
- MCP resources: `service-lane://demo-guide` and `vehicle://{serial}`.
- MCP tools remain read-only. Draft tools return text with `sent: false` / `submitted: false`; they do not contact anyone or change records. The local REST mileage route is the sole write path; it replaces mileage with advisor-entered date/source for known synthetic records in Supabase.
- Next.js proxies `/api/copilot/*` to FastAPI using `frontend/next.config.ts`.
- Next.js development allows the `127.0.0.1` loopback alias in `allowedDevOrigins`; without it, opening the app at `127.0.0.1:3000` can return 403 for Next client assets/HMR and leave the UI non-interactive. Both localhost addresses must be verified after frontend config changes.
- In-app chat exposes `GET /api/chat/models` and `POST /api/chat`; model discovery and inference are fixed to Ollama at `http://127.0.0.1:11434` with no cloud fallback.
- Local Ollama HTTP requests use a configurable timeout (`OLLAMA_TIMEOUT_SECONDS`, default 600 seconds, bounded to 30–1800 seconds); chat model selection omits embedding-only model names and chooses an installed chat model by default.
- Chat requests send `think: false`. On 2026-11-05 the user's machine ran `qwen3.5:4b` CPU-only (`size_vram: 0`); with thinking on, the turn exceeded the old 180 s timeout, while one tool request with `think: false` returned the correct `get_vehicle_record` call in 28.9 s.
- The MCP SDK 2.3 client wraps errors raised inside `async with Client(...)` in a nested `ExceptionGroup`. `chat_with_local_agent` unwraps Ollama errors so `/api/chat` returns 503 (unreachable), 504 (`OllamaTimeoutError`, model too slow) or 502 (Ollama error) instead of a generic 500. Covered by `backend/tests/test_local_agent.py`.
- The running backend must be restarted (or run with `--reload`) to pick up backend code changes; a server started without `--reload` keeps serving old code.
- `backend/app/local_agent.py` discovers MCP tools and resources in-process with the pinned MCP SDK, passes tool schemas to Ollama, reads advertised resources, and limits each turn to six tool rounds/twelve tool calls. It refuses an answer when the model uses no MCP capability.
- Topic guardrail (issue #24): the chat system prompt limits scope to dealership service-lane topics and asks for the exact marker `OUT_OF_SCOPE` otherwise. A reply containing the marker (case-insensitive, even after tool use) becomes `OUT_OF_SCOPE_REPLY` with `out_of_scope: true`; a reply with no MCP tool use becomes the scope message plus a serial-number hint. The model's off-topic text is never returned. Known gap: an off-topic answer given after a tool call without the marker is not detected.
- `frontend/app/chat-panel.tsx` keeps chat history in browser state only, offers models reported by local Ollama, and shows MCP capabilities used. Chat is not persisted server-side.
- Every synthetic vehicle now includes four demo telemetry streams: engine RPM (rpm), vehicle speed (km/h), coolant temperature (°C), and calculated engine load (%), each with four timestamped samples. The advisor page shows charts and an explicit simulated badge. MCP and local Ollama instructions prohibit treating these values as live OBD-II or recommendation evidence. No physical adapter/vehicle connection exists; live OBD-II/CAN remains future scope.

## Local run commands

Requirements: Node.js 20.9+, Python 3.11+, and a running Supabase instance (local Supabase CLI requires a Docker-compatible container runtime). Apply `supabase/migrations/`, set backend-only `SUPABASE_URL` and `SUPABASE_SECRET_KEY`, and run `python seed_supabase.py` from `backend/` to load or refresh the synthetic data. See README for detailed local and hosted setup.

Backend, from `backend/`:

```powershell
py -3 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`:

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`. For stdio MCP hosts, launch `<backend>/.venv/Scripts/python.exe <backend>/mcp_stdio.py`.

## Verified state and known gaps

- The source audit found a missing `date` import in the FastAPI mileage request model and a mismatch between the accepted replacement behavior and the missing-mileage-only form; issue #10 corrects both.
- Supabase database adapter tests and mileage API regression tests are under `backend/tests/`; `.github/workflows/verify.yml` runs backend tests and the frontend production build on pull requests and main pushes. GitHub Actions run 9 passed both jobs for commit `40654ab0be476325a6e260fc3dfb8fbaf0a1bead`.
- GitHub Actions run 42035577954 on main exposed a stale OBD telemetry test that called the removed `load_vehicles.cache_clear()` API and expected JSON-backed runtime storage. Issue #16 and PR #17 update the test to validate the seed fixture and use a fake Supabase store. GitHub Actions run 42041434835 passed both backend regression checks and the frontend production build for the PR head.
- The acceptance and verification plan is in `SERVICE_LANE_COPILOT_SPEC.md` and `docs/feature-spec-local-ollama-chat.md`. Live check on 2026-11-05 (issue #18 branch, backend with `think: false`): `POST /api/chat` with `qwen3.5:4b` on CPU returned HTTP 200 in 2m43s, called `get_vehicle_record`, and reported NS-2048's recorded statuses, rule, and evidence, labelling telemetry as simulated. Other models (`qwen3:1.7b`, `qwen3.5:9b`), resource reads, draft flows, and the in-browser chat UI were not exercised live.
- Do not assume the MCP mount, tools, UI, or API are runtime-verified based on source inspection alone.
- No live OBD-II/CAN integration, dealership history integration, authentication, hosted deployment, or real maintenance catalog exists.
- Numeric success targets are open until advisor baseline measures are captured.
- Agent instructions (issue #25): root `CLAUDE.md` imports `@AGENTS.md`, so Claude Code and other agents share one rule set; `AGENTS.md` now requires updating the spec/feature spec, `MEMORY.md`, and `CONTEXT.md` with each new requirement and change in the same PR. `frontend/AGENTS.md` is separate Next.js-generated guidance.

## Update rule

After a task, update this file only with facts confirmed from code, commands, or user decisions. Record unresolved items as open; never turn a proposed default into an approved requirement without user direction.
