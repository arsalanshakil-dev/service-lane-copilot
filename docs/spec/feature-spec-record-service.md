# Feature spec: Record completed services

Status: Approved (user request 2026-11-05, issue #28)
Owner: Service Lane Copilot
Updated: 2026-11-05

## User and problem

- User/role: Service advisor.
- Current task or pain: After an oil change or any other service is done, the advisor cannot record it. The vehicle keeps showing the item as Due, and the service history is out of date.
- Evidence or assumptions: Records live in Supabase `public.vehicle_records` as a JSON document with `history` events and stored demo `recs`. The app never calculates service intervals.

## Outcome and success measure

- Expected outcome: The advisor records a completed service in a few clicks. It is saved to Supabase, appears in the service history, and a matching stored recommendation shows **Completed**.
- Measure and baseline: A later lookup returns the new history event and status. No numeric target.

## Scope

### In scope

- Local REST route `POST /api/vehicles/{serial}/services` with body:
  - `serviceName` (1–80 characters, required)
  - `serviceDate` (ISO date, not in the future, required)
  - `mileage` (integer ≥ 0, or `null` when the odometer was not read)
  - `detail` (optional note, up to 200 characters)
  - `recommendationName` (optional; must exactly match a stored recommendation on the record)
- Insert a history event `{date: "Mon DD, YYYY", name, detail, mileage: "N mi" | "Not recorded", source: "advisor_recorded"}` in newest-first date order.
- When `recommendationName` is given, set only that recommendation to `status: "Completed"`, `kind: "done"`, with completion text and evidence (date, odometer, advisor-recorded). Its rule text is kept. Other recommendations are unchanged.
- If `mileage` is higher than the current recorded mileage, or none is recorded, set current mileage to it with `mileageDate` = service date and `mileageSource` = `advisor_observed`. A lower or missing service mileage leaves current mileage unchanged.
- Recompute the existing `conflicting` flag the same way as the mileage route (current mileage below a recorded service mileage).
- UI: **✓ Mark as done** on each stored recommendation that is not completed, and **+ Record service** in Service history. Both open a small form (date defaults to today, odometer defaults to current mileage, optional note). On save, the page shows the updated record, refreshes the template draft, and clears stale AI output.

### Out of scope

- Calculating the next due date or mileage, or creating new recommendations.
- Editing or deleting history events, or undoing a completion.
- Changing the `incomplete` flag (missing history elsewhere stays missing).
- Any MCP or chat write capability. MCP tools and the chat stay read-only.
- Prices, parts, labor, or invoices.

## Data and source of truth

- Authoritative source: the advisor's entry, stored with `source: advisor_recorded` on the history event.
- Missing/stale/conflicting data: unknown serial → 404; invalid input → 422 with no write. A service mileage below an older history entry is not reconciled; the existing conflict flag only compares current mileage with recorded service mileages.

## Safety, privacy, and approval

- Potential harm if wrong: a service recorded on the wrong vehicle or with a wrong odometer hides a due item. The advisor confirms the form before saving; completed items show their evidence.
- Completing a safety-related recommendation records that the work was done; it is not a diagnosis.
- External actions: local REST → Supabase via the backend secret key only. No outside service.

## Acceptance criteria

1. A valid service for a known record is saved to Supabase and the updated record is returned; a later lookup shows it.
2. Unknown serial → 404 with no write. Future date, negative or fractional odometer, empty or overlong name or note, and an unknown `recommendationName` → 422 with no write.
3. The history event is inserted in newest-first order and marked `advisor_recorded`.
4. A completed recommendation shows **Completed** with evidence; other recommendations are unchanged; template drafts stop listing it as due or coming up.
5. A higher odometer updates current mileage and provenance; a lower or missing odometer does not.
6. MCP exposes no write tool.

## Verification plan

- Automated: `backend/tests/test_record_service.py` (data-store and route checks against a fake Supabase client); frontend `tsc --noEmit`.
- Live: record a service on a synthetic vehicle through the frontend proxy and re-read it from Supabase.

## Open questions

- None. Undo/edit of recorded services can be specified later if needed.
