# Feature spec: Editable maintenance rules

Status: Approved (user request and decisions 2026-11-06, issue #47)
Owner: Service Lane Copilot
Updated: 2026-11-06

## User and problem

- User/role: Service advisor or demo administrator.
- Request: "rules configuration in the settings tab."
- Decisions: **editable mileage rules**, stored **in the database** for the whole app; the app **computes** Due / Coming up from each vehicle's recorded history and mileage; rules stay labelled demo rules; every rule change is logged. Starting set: 8 common services. The user applies the database migration by pasting SQL into the Supabase SQL Editor.

## Rules

Table `public.service_rules` (migration `supabase/migrations/20261106000100_create_service_rules.sql`, same RLS/grants as `vehicle_records`):

| Column | Meaning |
|---|---|
| `id` | slug, primary key (e.g. `engine-oil-and-filter`) |
| `service_name` | name shown on recommendations and matched against history entries |
| `coming_up_miles` | miles since last service from which the item is **Coming up** |
| `due_miles` | miles since last service from which the item is **Due** (`0 ≤ coming_up_miles < due_miles ≤ 200,000`) |
| `safety` | safety-related: shown as **Advisor verification**, never a diagnosis |
| `enabled` | disabled rules are ignored |
| `change_log` | list of `{at, action, actor, summary}`, latest 100 |

Starting demo rules: Engine oil and filter 4,000/5,000 · Tire rotation 6,000/7,500 · Vehicle inspection 10,000/12,000 · Brake inspection 12,000/15,000 (safety) · Cabin air filter 12,000/15,000 · Wiper blades 10,000/12,000 · Battery test 16,000/20,000 · Engine air filter 25,000/30,000 (coming up / due, miles since last service).

## How recommendations are computed

For each enabled rule, on every read:

1. The record must have current mileage and must not be incomplete or conflicting; otherwise recommendations stay paused (unchanged behaviour).
2. Find the newest history entry whose service name matches the rule (keyword match that ignores generic words such as "check", "inspection", "service", "replacement"; e.g. "Brake inspection" matches the rule "Brake inspection", "Wiper blades" matches "Wiper blade check"). If that entry has no readable mileage, or no entry matches, the rule produces nothing (no evidence → no claim).
3. `miles_since = current mileage − entry mileage`. `≥ due_miles` → **Due**; `≥ coming_up_miles` → **Coming up**; otherwise nothing. A safety rule shows **Advisor verification** instead.
4. Evidence: "Last recorded at X mi (date) · Current recorded mileage Y mi · Z mi since service". Rule text: "Demo rule: due at N mi since last service; coming up from M mi." `source: rule`, `ruleId`.

The vehicle's recommendations are then **rule-computed items + stored Advisor-entered items** (each Advisor-entered item carries `index`, its stored position, for edits). Legacy stored recommendations from the seed data are ignored while rules are available; they stay in the database untouched.

If the rules table is missing or unreadable, the app shows the stored recommendations as before and sets `rulesStatus: "unavailable"`, and the UI explains that the rules migration has not been applied. No other fallback exists.

Applied everywhere recommendations are read: vehicle API, records list counts, drafts, AI summary "Needs now", AI suggestions, MCP `get_vehicle_record` / `vehicle://` resource / draft tool, and the chat.

**Mark as done** on a rule item records the service; the rule then recomputes from the new history entry (so the item disappears until it is due again). On an Advisor-entered item it also marks that item Completed (unchanged).

## Rules API and Settings

- `GET /api/rules`, `POST /api/rules` (add), `PUT /api/rules/{id}` (edit; body includes `expectedUpdatedAt`, stale → 409). No delete: rules are disabled instead. Duplicate service names (case-insensitive) → 409; invalid numbers → 422. Each change appends to the rule's change log (actor "advisor (web app)").
- Settings → **Maintenance rules**: table of rules with Edit (service name, coming up from, due at, safety, enabled), **+ Add rule**, and each rule's change log. Labelled "Demo rules — not manufacturer schedules".
- MCP: rules are read-only for now (shown inside computed recommendations); no rule-editing MCP tools in this ticket.

## Out of scope

Time-based (months) rules, per-make/model rules, deleting rules, MCP rule editing, real manufacturer schedules.

## Acceptance criteria

1. With the migration applied, NS-2048 shows rule-computed items with evidence and rule text; changing a rule's mileage changes Due / Coming up on the next read.
2. Recording a service makes that rule's item disappear until it is due again.
3. Advisor-entered recommendations still show and can be edited/removed.
4. Incomplete or conflicting records show no rule items (paused).
5. Without the migration, the app shows stored recommendations and a clear "rules not set up" notice.
6. Rule add/edit validates input, rejects stale edits and duplicates, and logs every change.
7. Tests cover the engine, API, and fallback; the README explains how to apply the migration.
