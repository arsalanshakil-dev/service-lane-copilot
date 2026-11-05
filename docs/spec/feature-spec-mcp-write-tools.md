# Feature spec: MCP write tools and advisor-confirmed chat changes

Status: Approved (user requests and decisions 2026-11-05/06, issue #44)
Owner: Service Lane Copilot
Updated: 2026-11-06

## User and problem

- User/role: Service advisor, and MCP-compatible agent tools on the same computer.
- Request: "Have MCP able to update and edit as well as add records" and "don't forget to write MCP tools as well."
- Decision: **Chat proposes, you confirm.** Outside MCP agents may write directly; in the in-app chat a write happens only after the advisor clicks Apply on a preview card. Every write is logged.
- Later decision (2026-11-06): service history can be **edited but never deleted**, in the API, UI, and MCP.

## Scope

### MCP write tools (local MCP endpoint only)

| Tool | Effect |
|---|---|
| `add_vehicle` | New synthetic vehicle (same rules as `POST /api/vehicles`) |
| `update_vehicle_details` | Make, model, year; optional serial rename |
| `update_vehicle_mileage` | Replace current mileage (date not in the future) |
| `record_completed_service` | Add a history entry; optionally mark a stored recommendation Completed |
| `edit_history_entry` | Replace one history entry (index + expected date/name) |
| `add_recommendation`, `update_recommendation`, `remove_recommendation` | Advisor-entered recommendations (index + expected name for edits) |

- All tools go through `backend/app/mcp_writes.py`, which validates input and calls the same functions as the REST API (`record_edits.py`, `data_store.py`). Stale or invalid requests return `{"saved": false, "error": …}` and write nothing.
- Successful writes return a compact vehicle summary and the change-log entry. Change-log actor: **"MCP agent"**.
- There is no history-delete tool or route.

### In-app chat (local Ollama model)

- When the model calls a write tool, the backend does **not** run it. It stores a proposal (random id, single use, expires after 15 minutes) and tells the model "PROPOSED, NOT SAVED", so it cannot claim a save.
- The chat response includes `proposals`; the panel shows a confirm card per proposal with **Apply change** and **Discard**.
- `POST /api/chat/proposals/{id}/apply` validates and saves once (actor **"advisor via chat (confirmed)"**); unknown, used, or expired ids return 404; invalid content returns 422 without writing. `DELETE /api/chat/proposals/{id}` discards.
- After Apply, an open vehicle with that serial refreshes.

### Unchanged boundaries

- MCP stays on localhost. Draft tools still never send, submit, or book. No external services, vehicles, or real data. Telemetry remains simulated and is never written.

## Acceptance criteria

1. Each MCP write tool saves valid input and logs actor "MCP agent"; invalid, unknown, or stale input returns `saved: false` without writing.
2. A chat write request never writes before Apply; Apply writes once; a second Apply, unknown, or expired id returns 404; Discard removes it.
3. Read tools, resources, and draft tools behave as before.
4. Service history cannot be deleted through REST, UI, or MCP.

## Verification plan

- Automated: `backend/tests/test_mcp_writes.py`, updated `test_record_service.py` and `test_edit_records.py`.
- Live: chat with the local model on a synthetic test vehicle → proposal shown, nothing saved → Apply → saved and logged; test vehicle removed afterwards.
