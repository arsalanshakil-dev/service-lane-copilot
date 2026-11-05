# Feature spec: Supabase vehicle-record database

Status: Approved  
Owner: Service Lane Copilot  
Updated: 2026-11-05

## User and problem

- User/role: multiple dealership service advisors using the local app.
- Current pain: vehicle records and approved manual mileage updates currently live in one local JSON file, so changes are not a shared persistent database.
- Evidence/assumption: the user asked to use Supabase as the database. This feature supports either a hosted Supabase project or local Supabase stack via environment configuration. No hosted project or credentials have been supplied.

## Outcome and success measure

- FastAPI reads and persists vehicle records through Supabase Postgres.
- The existing REST/MCP vehicle record shape remains stable.
- Local developers can create a database using checked-in migrations and load the 250 synthetic fixture records.
- Database availability/configuration failures are explicit and never silently fall back to local JSON.

## Scope

### In scope

- Use the official Supabase Python client only in the Python backend.
- Create one `public.vehicle_records` table keyed by normalized vehicle serial, containing the existing structured vehicle record as JSONB plus an `updated_at` timestamp. This preserves the existing record contract while moving the runtime source of truth to Postgres.
- Enable RLS and revoke direct access for public/anonymous/authenticated API roles; grant backend service access only. Keep the server secret in `backend/.env`, which is ignored by Git.
- Add an idempotent seed command to upsert the existing synthetic `data/vehicles.json` fixtures.
- Use Supabase for REST, MCP, and local chat record reads and for the advisor-approved synthetic mileage update.
- Support local and hosted Supabase through `SUPABASE_URL` and `SUPABASE_SECRET_KEY`; do not provision or mutate a hosted project in this feature.
- Add safe configuration/database failure responses, regression checks, setup instructions, and architecture/file-map updates.

### Out of scope

- Loading or processing real customer, production dealership, or real vehicle data.
- Provisioning a hosted project, setting hosted secrets, or applying migrations to a hosted database.
- Adding browser Supabase clients, exposing database credentials, adding user sign-in, or changing the existing local-only API/MCP binding.
- CSV import/export, DMS connectors, physical OBD-II, migrations of production data, or changing the customer-draft workflow.

## User workflow

1. Start a local Supabase stack or select an existing hosted project.
2. Apply the checked-in schema migration and place the URL and server key in the ignored `backend/.env`.
3. Run the seed command to populate the 250 synthetic fixtures.
4. Start FastAPI and Next.js; advisor and MCP lookups read the same Supabase-backed record.
5. Advisor-approved mileage replacement persists to the same vehicle row and preserves the remaining record fields.

## Data and source of truth

- Inputs: Supabase URL/server secret and the repository's synthetic JSON fixture used only by the seed command.
- Authoritative runtime source: the `vehicle_records` Postgres table.
- Lookup key: uppercase synthetic serial string, unique primary key.
- Missing/stale/conflicting data: preserve existing app behavior and evidence gates. Unknown serials remain unknown. Database/configuration/network failures report unavailable; there is no JSON runtime fallback.
- Data retained/emitted: the complete current vehicle record JSON, including mileage provenance, service history, explicit demo recommendations, and simulated telemetry, plus database update timestamp.

## Safety, privacy, and approval

- The user-supplied project key is a backend secret. Never place it in Next.js source, browser configuration, logs, repository files, or chat.
- Supabase RLS is enabled; `anon`, `authenticated`, and `PUBLIC` receive no table privileges or policies. Only backend server access is granted.
- The FastAPI backend remains bound to localhost for the demo. Do not expose it to a LAN or public network in this feature.
- MCP remains read-only. Only the existing advisor-reviewed REST mileage endpoint may update synthetic records.
- Use synthetic data only. Do not seed the database with real dealership records.

## Failure cases

- Missing URL/key: give a clear setup error and HTTP 503 for database-backed API operations.
- Supabase unreachable, invalid credential, table/migration missing, or query failure: give a generic 503 database-unavailable message without returning secrets or raw provider errors to the user.
- Empty table: report zero records; offer the documented seed command, without falling back to JSON.
- Unknown serial: return existing 404/not-found behavior and do not create a row.
- Mileage update to unknown serial: return 404; database error: 503; success: preserve all non-mileage JSON fields.
- Seed rerun: upsert the same synthetic records by serial; never connect to live dealership sources.

## Acceptance criteria

1. A checked-in Supabase migration creates `public.vehicle_records`, a serial primary key, JSONB record validation, `updated_at`, RLS, and least-privilege grants.
2. An idempotent backend seed command imports the existing synthetic fixture to Supabase and reports the loaded count; no runtime code reads the fixture.
3. Known serial lookup returns the same complete record through REST and MCP. Unknown serials remain not found.
4. Mileage replacement writes the new mileage/date/source to Supabase, preserves history/recommendations/telemetry and conflict behavior, and never writes the JSON fixture.
5. Missing configuration and provider errors are clear 503 responses without sensitive error details. There is no silent fallback.
6. Frontend code contains no Supabase client or secret. API/MCP remain local and read-only except for the existing REST mileage path.
7. Mocked backend tests cover configuration, known/unknown lookup, search, seed idempotency, update preservation, and database errors.
8. README, CONTEXT, spec, memory, and folder/file guide distinguish the runtime database from the seed fixture.
9. Backend regression tests and frontend production build pass.

## Verification plan

- Automated: `python -m unittest discover -s tests -v` from `backend/`; `npm run build` from `frontend/`.
- Database integration: with local Supabase running, apply migrations, seed twice, verify row count stays 250, read known/unknown serials, update mileage and confirm other JSON fields are unchanged.
- Security review: confirm RLS/revokes/grants in migration, confirm `backend/.env` ignored, scan frontend and Git diff for keys, verify no JSON runtime fallback, network binding unchanged.

## Implementation plan

1. Add this feature spec and update the main product spec.
2. Add schema migration, backend Supabase adapter, runtime error handling, and seed command.
3. Add backend adapter tests and pin required dependencies.
4. Update API capabilities and document hosted/local setup.
5. Update README architecture/tree/file guide, context, and memory.
6. Run CI checks; leave the PR open for human review.

## Open questions

- A Supabase project URL/key is needed to connect this local app to an existing hosted project. Do not send keys in chat; enter them in the ignored local environment file.
