# Instructions for coding agents

These instructions apply to every coding agent. Claude Code loads them through `CLAUDE.md`, which imports this file; edit this file, not `CLAUDE.md`.

## Read before changing code

1. Read `SERVICE_LANE_COPILOT_SPEC.md` for product behavior and acceptance criteria.
2. Read `MEMORY.md` for the current verified architecture, commands, and known gaps.
3. Inspect the implementation and data files that the task will affect. Do not assume the memory is newer than the code; correct memory when verified facts differ.

## Source of truth

- The user's current explicit request controls the task.
- `SERVICE_LANE_COPILOT_SPEC.md` and linked feature specs define approved product behavior.
- This file defines the development process and safety rules.
- `MEMORY.md` is a compact continuity aid. It must not add product requirements or override the spec.
- `CONTEXT.md` is the onboarding overview. It summarizes the project and must not create or override requirements.
- When a request changes behavior, update the spec before implementation. If scope or safety is unclear, ask a focused question before implementing the uncertain part.

## Ticket, branch, and pull request workflow

For every project task that changes project files—including documentation, configuration, data, or code—use this workflow:

1. Create a new ticket in the project's configured issue tracker before making project changes. Include the request, scope, and observable acceptance criteria. Link the ticket from the branch and pull request.
2. Create a dedicated branch from the current `main` branch and do all task work on that branch, using an isolated worktree when available. Never make task changes directly on `main`.
3. Implement the ticket, run the required checks, and update the relevant specs, `MEMORY.md`, `CONTEXT.md`, README diagrams, folder tree, and file guide as described in the required workflow below.
4. Open a pull request from the task branch into `main`. Include the ticket link, a concise change summary, check results, and any unverified items.
5. Leave the pull request open for human review. Do not self-approve, bypass required checks, or merge before a human reviewer has approved it. Address requested changes and request review again.
6. After human approval is recorded, merge the pull request into `main` using the repository's normal protected-branch process. Do not bypass branch protections or merge if required approvals/checks are missing.

If the issue tracker, Git repository, remote, or pull request service is unavailable or not configured, stop before making the requested project change and ask the user to connect or identify the required service. Do not silently skip the ticket, branch, review, or merge stages.

## Required workflow

For every project change on its ticket branch:

1. Turn the request into specific acceptance criteria before editing. Use `docs/spec/feature-spec-template.md` for a distinct feature and save the new spec as `docs/spec/feature-spec-<name>.md` (all feature specs live in `docs/spec/`; other material stays in `docs/`); update the main spec for changes to existing behavior.
2. List the smallest implementation tasks and files likely to change. Keep one task focused per session.
3. Implement only specified behavior. Avoid unrelated refactors, speculative integrations, unrequested dependencies, and hidden external actions.
4. Add or update automated checks for changed behavior. At minimum, backend data/API/MCP changes need checks for known and unknown records, data limitations, correct evidence, and no side effects. Frontend changes need type/build checks and relevant interaction checks.
5. Run checks required by the spec when the environment allows. If a check cannot run, report it as unverified with the concrete blocker; never substitute a guess for a passing result.
6. Review the complete diff for unsupported claims, generated data leaks, access expansion, unsafe commands, and changes outside the task.
7. Keep the project documents in step with every new requirement and every change, in the same branch and pull request:
   - When a new requirement or user decision is accepted, record it in `SERVICE_LANE_COPILOT_SPEC.md` and the relevant feature spec in `docs/` **before** implementing it.
   - After the change, update the spec and feature spec with the final behavior and acceptance criteria, `MEMORY.md` with verified decisions, implementation state, live-check results, and open gaps, and `CONTEXT.md` whenever the project overview, advisor workflow, boundaries, or document map changes.
   - **Update `README.md` with every change, together with the spec, feature spec, `MEMORY.md`, `CONTEXT.md`, and `AGENTS.md`** (user rule, 2026-11-06): features and how to use them, setup and run steps, endpoints and MCP tools, the architecture diagram, folder tree, and key-file guide. Check the README against the implementation before opening the pull request.
   - Do not record assumptions as facts. If a document (including the README) needs no change, say so explicitly in the pull request.
8. Keep the architecture diagram, folder tree, and key-file guide in `README.md` current whenever a change adds, removes, or moves a component, source folder, or important project file. Update them in the same change and verify they match the implementation.

## Project safety rules

- Use synthetic data only in the demo. Never add client, customer, production, or real vehicle records, credentials, or secrets.
- Supabase Postgres is the runtime source of truth for synthetic vehicle records; `data/vehicles.json` is only an importable seed fixture. Never add a JSON runtime fallback.
- Keep `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in the Python backend environment only. Never expose a Supabase secret key to the frontend, browser bundle, logs, screenshots, or chat.
- Keep all recommendation content grounded in explicit record fields and synthetic demo rules. Show evidence. Missing, stale, or contradictory data means uncertainty and advisor follow-up.
  - Approved exception (user decision 2026-11-05, issue #42): an advisor may add or edit recommendations by hand through the REST API/UI. These are stored with `source: advisor_entered`, labelled "Advisor-entered" with the advisor's own evidence text, never generated by a model, and recorded in the record's change log.
- Every REST write to a vehicle record must append a change-log entry (time, action, actor, summary) to that record.
- Demo rules are not real maintenance advice. Safety-related items are verification prompts, not diagnoses.
- MCP write tools (approved 2026-11-06, issue #44) may add and edit synthetic vehicle records only through `backend/app/mcp_writes.py`: validated input, stale-edit guards, and a change-log entry (actor "MCP agent"). The in-app chat model must never write directly; its write calls become proposals that run only after the advisor clicks Apply (actor "advisor via chat (confirmed)"). Service history may be edited but never deleted. Draft tools may create text in memory and return it, but must never send, submit, book, call an outside service, or control a vehicle.
- The MCP HTTP endpoint stays on localhost for this demo. Do not bind publicly, expose a new network interface, add authentication bypasses, or publish it without a separate spec and security review.
- Physical OBD-II/CAN access remains future scope. The approved demo includes synthetic simulated telemetry only when required by `SERVICE_LANE_COPILOT_SPEC.md`; label it clearly, keep it read-only, and never treat it as live data, mileage, service history, diagnostic evidence, or a basis for recommendations. Do not add hardware access, ECU commands, VIN decoding services, manufacturer-specific PIDs, or physical vehicle assumptions without a separate feature spec. Any later vehicle connection must be read-only and handle unsupported or conflicting fields explicitly.
- Do not invent prices, maintenance intervals, external history, or vehicle attributes. Unknown values stay unknown.
  - Approved exception (user decision 2026-11-05, issue #30): **AI suggestions only** may show a local model's estimate of a typical service interval in miles. It must be labelled as an unverified model estimate, shown separately from stored recommendations, never used to change stored recommendation status, and the backend must still block prices and drop items repeated too soon after a recorded service. Stored recommendations, drafts, and chat replies remain bound by the rule above.
- Keep package versions pinned. Before adding or updating a dependency, check the official source and compatibility, explain the need in the spec, and update the lock file when the package manager is available.
- Do not run destructive or externally consequential actions as part of local development. Keep commands scoped to this project.

## Completion report

Report the changed behavior, the files that define it, checks that passed, checks not run, and remaining decisions. “No issues” is never a substitute for listing evidence and limitations.
