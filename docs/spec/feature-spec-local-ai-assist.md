# Feature spec: Local AI customer drafts and AI-suggested service items

Status: Approved (user decision 2026-11-05, issue #22)
Owner: Service Lane Copilot
Updated: 2026-11-05

## User and problem

- User/role: Service advisor.
- Current task or pain: Template drafts read the same for every vehicle, and the stored demo recommendations cover only a few items. The advisor wants the local Ollama model to write customer drafts and to suggest further service items worth reviewing.
- Evidence or assumptions: The user chose (1) instant template drafts on lookup plus an on-demand local-AI draft button, and (2) model-suggested service items in addition to the stored demo recommendations. On the user's CPU-only machine one `think: false` Ollama call takes roughly 30–90 seconds.

## Outcome and success measure

- Expected outcome: The advisor can replace the active template draft with an Ollama-written draft, and can request up to three AI-suggested service items that are clearly separated from the stored recommendations and cite recorded service history.
- Measure and baseline: No numeric target. Every displayed AI suggestion cites at least one real history entry; no displayed suggestion or draft contains a price.

## Scope

### In scope

- `POST /api/vehicles/{serial}/ai-draft` with `{model, draftType}` (`explanation`, `quote`, `followup`): one local Ollama call that rewrites the stored-record template draft in natural language.
- `POST /api/vehicles/{serial}/ai-suggestions` with `{model}`: one local Ollama call with a JSON-schema `format`, returning up to three AI suggestions after backend validation.
- Frontend: a local-AI model selector and **Generate with local AI** button in the Customer drafts panel; a **Suggest more with local AI** button and a separate, labelled AI-suggestions section under the stored recommendations.
- Ollama access reuses the existing loopback-only client (`127.0.0.1:11434`), `think: false`, installed-model check, `OLLAMA_TIMEOUT_SECONDS`, and the 503/504/502 error mapping.

### Out of scope

- Changing, removing, re-ranking, or re-labelling stored recommendations.
- Persisting AI drafts or suggestions, sending drafts, booking work, or writing records.
- New MCP tools; cloud models; prices or labor times. (Maintenance intervals were out of scope until issue #30; AI suggestions may now show a labelled model estimate.)
- Using simulated telemetry as evidence (it is excluded from the model prompt).

## Guardrails (validation performed by the backend)

AI suggestions:

1. Each suggestion must reference one or more recorded service-history entries by number. Out-of-range or missing references → dropped. Evidence text is built by the backend from the referenced entries and the recorded mileage, never from model text.
2. A suggestion whose name or reason contains a price/currency → dropped.
3. ~~A suggestion stating an interval is dropped.~~ Superseded by issue #30: the model returns `typical_interval_miles` (its own unverified estimate). The backend shows it as "Model estimate: about every N mi. Unverified; check the manufacturer schedule." and drops the suggestion when a matching recorded service was done fewer miles ago than that estimate or the 1,000 mi demo floor (or within 30 days when its odometer was not recorded). An item with no matching recorded service is dropped while the vehicle's current mileage is below the model's interval estimate (not due yet). Matching compares service-name keywords (for example "Wiper blade check" matches "Wiper blades").
4. A suggestion that duplicates a stored recommendation or an earlier suggestion (case-insensitive name match or containment) → dropped.
5. At most three suggestions are returned. The number dropped is reported.
6. Safety-related suggestions (model flag or keywords such as brake, tire, steering, suspension, airbag, seat belt, recall, light, leak) are marked safety and shown as verification prompts, not diagnoses.
7. Every suggestion has status "AI suggestion — unverified" and a note naming the local model and stating it is not from the demo schedule.
8. Records with no service history, missing mileage, or flagged incomplete/conflicting data return no suggestions and a limitation message, without calling Ollama.

AI drafts:

1. The prompt contains only the record's identity, recorded mileage, history, stored recommendations (status, evidence, rule), and the template draft; it excludes telemetry.
2. A draft containing a price/currency is rejected with an actionable error; the advisor can regenerate or keep the template.
3. Empty model output is rejected. Drafts are returned with `sent: false` and are editable text only.

## Failure cases

- Unknown serial → 404 before any Ollama call.
- Model not installed → 502 with the existing message.
- Ollama unreachable → 503; model exceeds timeout → 504; invalid model output → 502.
- In every failure the template draft and stored recommendations remain visible and usable.

## Acceptance criteria

1. Lookup shows the instant template draft; **Generate with local AI** replaces the active draft with model text labelled as local-AI-written, editable, and never sent.
2. **Suggest more with local AI** shows up to three AI suggestions in a separate labelled section with backend-built evidence from cited history entries.
3. Invalid suggestions (bad reference, price, duplicate, or repeated too soon after a recorded service) are dropped and the dropped count is shown.
4. Incomplete, conflicting, missing-mileage, or no-history records return a limitation and no suggestions, with no Ollama call.
5. Unknown serials return 404 without an Ollama call. Nothing is written to Supabase.
6. Ollama errors show a clear message and the rest of the page stays usable.

## Verification plan

- Automated checks: `backend/tests/test_ai_assist.py` (validation rules, grounding, known/unknown/incomplete records, no Supabase writes, `think: false`, API error mapping); frontend `tsc --noEmit`.
- Manual: one live AI draft and one live suggestion request against local Ollama.

## Open questions

- None. Real (manufacturer) maintenance schedules and pricing remain out of scope; model interval estimates are labelled unverified.
