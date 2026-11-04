# Instructions for coding agents

## Read before changing code

1. Read `SERVICE_LANE_COPILOT_SPEC.md` for product behavior and acceptance criteria.
2. Read `MEMORY.md` for the current verified architecture, commands, and known gaps.
3. Inspect the implementation and data files that the task will affect. Do not assume the memory is newer than the code; correct memory when verified facts differ.

## Source of truth

- The user's current explicit request controls the task.
- `SERVICE_LANE_COPILOT_SPEC.md` and linked feature specs define approved product behavior.
- This file defines the development process and safety rules.
- `MEMORY.md` is a compact continuity aid. It must not add product requirements or override the spec.
- When a request changes behavior, update the spec before implementation. If scope or safety is unclear, ask a focused question before implementing the uncertain part.

## Ticket, branch, and pull request workflow

For every project task that changes project files—including documentation, configuration, data, or code—use this workflow:

1. Create a new ticket in the project's configured issue tracker before making project changes. Include the request, scope, and observable acceptance criteria. Link the ticket from the branch and pull request.
2. Create a dedicated branch from the current `main` branch and do all task work on that branch, using an isolated worktree when available. Never make task changes directly on `main`.
3. Implement the ticket, run the required checks, and update the relevant specs, memory, README diagrams, folder tree, and file guide as needed.
4. Open a pull request from the task branch into `main`. Include the ticket link, a concise change summary, check results, and any unverified items.
5. Leave the pull request open for human review. Do not self-approve, bypass required checks, or merge before a human reviewer has approved it. Address requested changes and request review again.
6. After human approval is recorded, merge the pull request into `main` using the repository's normal protected-branch process. Do not bypass branch protections or merge if required approvals/checks are missing.

If the issue tracker, Git repository, remote, or pull request service is unavailable or not configured, stop before making the requested project change and ask the user to connect or identify the required service. Do not silently skip the ticket, branch, review, or merge stages.

## Required workflow

For every project change on its ticket branch:

1. Turn the request into specific acceptance criteria before editing. Use `docs/feature-spec-template.md` for a distinct feature; update the main spec for changes to existing behavior.
2. List the smallest implementation tasks and files likely to change. Keep one task focused per session.
3. Implement only specified behavior. Avoid unrelated refactors, speculative integrations, unrequested dependencies, and hidden external actions.
4. Add or update automated checks for changed behavior. At minimum, backend data/API/MCP changes need checks for known and unknown records, data limitations, correct evidence, and no side effects. Frontend changes need type/build checks and relevant interaction checks.
5. Run checks required by the spec when the environment allows. If a check cannot run, report it as unverified with the concrete blocker; never substitute a guess for a passing result.
6. Review the complete diff for unsupported claims, generated data leaks, access expansion, unsafe commands, and changes outside the task.
7. Update the spec and `MEMORY.md` with verified decisions, implementation state, and open gaps. Do not record assumptions as facts.
8. Keep the architecture diagram, folder tree, and key-file guide in `README.md` current whenever a change adds, removes, or moves a component, source folder, or important project file. Update them in the same change and verify they match the implementation.

## Project safety rules

- Use synthetic data only in the demo. Never add client, customer, production, or real vehicle records, credentials, or secrets.
- Keep all recommendation content grounded in explicit record fields and synthetic demo rules. Show evidence. Missing, stale, or contradictory data means uncertainty and advisor follow-up.
- Demo rules are not real maintenance advice. Safety-related items are verification prompts, not diagnoses.
- The MCP tools must remain read-only. Draft tools may create text in memory and return it, but must never send, submit, book, write a record, call an outside service, or control a vehicle.
- The MCP HTTP endpoint stays on localhost for this demo. Do not bind publicly, expose a new network interface, add authentication bypasses, or publish it without a separate spec and security review.
- OBD-II/CAN is future scope only. Do not add hardware access, ECU commands, VIN decoding services, manufacturer-specific PIDs, or mileage assumptions without a feature spec. Any later vehicle connection must be read-only and handle unsupported or conflicting fields explicitly.
- Do not invent prices, maintenance intervals, external history, or vehicle attributes. Unknown values stay unknown.
- Keep package versions pinned. Before adding or updating a dependency, check the official source and compatibility, explain the need in the spec, and update the lock file when the package manager is available.
- Do not run destructive or externally consequential actions as part of local development. Keep commands scoped to this project.

## Completion report

Report the changed behavior, the files that define it, checks that passed, checks not run, and remaining decisions. “No issues” is never a substitute for listing evidence and limitations.
