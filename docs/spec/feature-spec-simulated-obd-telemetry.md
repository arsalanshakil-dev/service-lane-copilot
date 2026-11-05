# Feature spec: Simulated OBD-II telemetry POC

Status: Approved  
Owner: Service Lane Copilot  
Updated: 2026-11-05

## User and problem

- User/role: dealership service advisor demonstrating the application.
- Current task: show how read-only vehicle telemetry could appear alongside a synthetic service record before physical OBD-II hardware is selected.
- Evidence or assumptions: this is a POC data visualization. No adapter, ECU, or vehicle is connected.

## Outcome and success measure

- Every synthetic vehicle lookup includes a few deterministic telemetry time series that appear in the API/MCP vehicle record and the advisor UI.
- Advisors can see sample trends and understand they are simulated. Telemetry must not be treated as mileage, service history, a fault diagnosis, or recommendation evidence.

## Scope

### In scope

- Add four clearly named simulated streams to all synthetic vehicle records (250 at the time; 1,000 since issue #34): engine RPM (rpm), vehicle speed (km/h), coolant temperature (°C), and calculated engine load (%).
- Include four timestamped sample points per stream, consistent units, deterministic values, and record-level simulation metadata.
- Display a compact trend chart for each stream on the vehicle details page, including latest value and sample time.
- Expose the record fields through existing REST and MCP record retrieval; no separate telemetry transport or write endpoint.
- Update requirements, agent instructions, context, memory, README diagrams/tree/file guide, and add automated regression checks.

### Out of scope

- Physical OBD-II adapter/CAN connection, ECU communication, vehicle commands, live telemetry, external services, diagnostic trouble codes, fault diagnosis, maintenance advice, and use of telemetry for recommendations or mileage.
- Replacing synthetic dealership service history or the advisor-approved manual mileage process.

## Scrollable recording (issue #52, 2026-11-06)

User request: scroll through recorded samples, because a real connection would record seconds to minutes of data. Approved defaults: 5 minutes at 1 sample per second.

- `GET /api/vehicles/{serial}/telemetry` returns a **simulated recording**: 300 samples per stream (1 Hz, 5 minutes) for the same four streams and units, ending at the record's `capturedAt`. Values follow a short-drive profile (idle → pull away → cruise → slow down → stop → short drive) with small deterministic variation seeded from the serial, so repeat calls return identical data. It is generated on request; nothing new is stored. Unknown serial → 404. Vehicles without stored telemetry still get a recording (it is simulated for every known vehicle).
- Value ranges stay within the existing checks: RPM 0–3,600, speed 0–100 km/h, coolant 0–120 °C, load 0–100 %.
- The telemetry panel shares one time window across the four charts: window sizes 15 s, 30 s, 1 min, 5 min; scroll with a slider, ◀ ▶ buttons, or arrow keys; hover shows the value and time in the Settings time zone; each chart shows min / max / average for the window. If the recording cannot load, the stored 4-sample streams are shown with a note.
- The stored 4-sample `obdTelemetry` in each record is unchanged (still returned by REST/MCP record retrieval).
- Same safety rules: labelled simulated everywhere, no adapter or vehicle access, never mileage, service-history, diagnostic, or recommendation evidence. Not exposed as an MCP tool in this change.

## User workflow

1. Advisor looks up any known synthetic serial number.
2. The vehicle details include a prominent “Simulated OBD-II · POC data only” section with four trends and units.
3. Advisor can distinguish this sample data from live vehicle readings and continue using dealership history and existing recommendation evidence separately.

## Data and source of truth

- Inputs: synthetic vehicle serials and fixed demo sample profiles stored in `data/vehicles.json`.
- Authoritative source: static synthetic data in the repository; it is not read from a vehicle.
- Missing/stale/conflicting-data behavior: if a record has no telemetry or an empty stream, show an explicit unavailable state. Never infer a replacement value.
- Data retained or emitted: simulated-only marker, source label, fixed capture/sample timestamps, stream key/label/unit, and numeric samples. Existing record lookup returns the fields; the app does not persist user interaction.

## Safety, privacy, and approval

- Potential harm if wrong: an advisor might mistake fictional values for live vehicle measurements or service evidence.
- Every surface labels the data simulated and says no adapter is connected.
- Telemetry is read-only and cannot change mileage, recommendations, history, or any vehicle field.
- No customer, production vehicle, or external data is used.

## Failure cases

- Unknown serial: existing explicit no-record response, with no telemetry invented.
- Missing telemetry or stream samples: render “No simulated telemetry samples available.”
- Malformed/non-finite values: frontend must not render a fabricated value; dataset regression checks reject invalid samples.
- Model/chat asks about telemetry: explain its simulated status and do not use it to justify service work.

## Acceptance criteria

1. All 250 records contain simulation metadata and exactly four documented streams, each with four timestamped numeric samples and the specified unit.
2. Sample values are deterministic and timestamps form the documented fixed sample window.
3. Known vehicle REST and MCP retrieval exposes the simulation marker and streams; an unknown vehicle remains not found.
4. The vehicle page shows a clear simulated warning, each stream’s unit/latest value/time, and a visual trend; missing telemetry has a clear unavailable state.
5. Neither recommendations, mileage, nor service history are calculated or modified from telemetry.
6. MCP instructions and local Ollama grounding explicitly state that telemetry is simulated and not recommendation evidence.
7. Regression checks cover all records, schema, units, timestamps, numeric/range validity, determinism, unknown lookup, and unchanged recommendation/mileage fields.
8. README, spec, memory, and coding-agent instructions agree that simulation is permitted for the demo and physical access remains out of scope.

## Verification plan

- Automated: run `python -m unittest discover -s tests -v` in `backend/`; build the frontend with `npm run build` in `frontend/`.
- Manual review: look up NS-2048 and a generated DEMO serial in light/dark themes; confirm four charts and simulation labeling; inspect an incomplete record and verify telemetry does not unpause recommendations.
- Security/data-boundary review: inspect diffs for physical OBD/CAN libraries, ECU writes, network requests, non-synthetic records, recommendation mutations, or write endpoints.

## Implementation plan

1. Add specification and revise the main product and agent rules.
2. Attach deterministic telemetry to every synthetic vehicle.
3. Return telemetry through existing read paths and reinforce local model grounding.
4. Add the telemetry display and styles.
5. Add backend regression checks and update project docs/memory.

## Open questions

- Physical OBD-II adapter and live integration remain future work and require a separate approved spec.
