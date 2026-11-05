# Feature spec: Local Ollama MCP chat assistant

Status: Approved  
Owner: Service Lane Copilot  
Updated: 2026-11-05

## User and problem

- User/role: Service advisor.
- Current task or pain: Use Service Lane Copilot's vehicle lookup, evidence, demo guide, and draft capabilities through conversation instead of navigating each UI flow.
- Evidence or assumptions: The current MCP server exposes five tools and two resources. The user requires local Ollama models only.

## Outcome and success measure

- Expected outcome: The advisor can ask about synthetic records and prepare unsent drafts in a chat panel in the app.
- Measure and baseline: A request can use every registered MCP tool and resource, and the interface shows which MCP tools were used. No numeric target is set.

## Scope

### In scope

- Add an in-app chat panel that uses a model installed in the local Ollama service. Since issue #40 the model is chosen once in Settings for the whole app; the chat panel shows it with a link to Settings instead of its own selector.
- Call Ollama only at `http://127.0.0.1:11434`; do not accept a configurable remote model URL or fall back to hosted inference.
- Use Ollama's local `/api/chat` tool-calling interface with `think: false`, so thinking-capable local models (for example qwen3/qwen3.5) return tool calls and replies without long hidden reasoning that can exceed the request timeout on CPU-only machines.
- Connect to the existing MCP server in-process through the pinned MCP Python SDK client; dynamically discover and call every registered MCP tool.
- Make all fixed MCP resources and resource templates available through a chat resource-reading function.
- Preserve a short conversation in browser state only; no chat persistence is added.
- Show actionable errors when Ollama is unavailable, no local model is installed, or the selected model cannot complete tool use.
- Distinguish a stopped Ollama service (HTTP 503) from a running model that exceeds the request timeout (HTTP 504, naming the timeout and suggesting a smaller model or a larger `OLLAMA_TIMEOUT_SECONDS`). Ollama errors raised while the in-process MCP client is open must reach these handlers rather than surfacing as a generic HTTP 500.
- Ground vehicle claims in tool/resource output and preserve the synthetic-data, evidence, uncertainty, and safety boundaries.
- Topic guardrail (issue #24): the system prompt limits the assistant to dealership service-lane topics and tells it to reply with the exact marker `OUT_OF_SCOPE`, without tools, for anything else. The backend replaces a reply containing the marker (even after tool use) with a fixed refusal and `out_of_scope: true`, and replaces any reply that used no MCP capability with the same scope message plus a hint to include a serial number. The model's off-topic text is never returned.
- Keep all drafts unsent and editable/copyable by the user.

### Out of scope

- Cloud or hosted models, external APIs, web search, cross-dealership history, physical vehicle access, or model downloads.
- New MCP write tools, record changes, message sending, booking, or repair authorization.
- Persisting chat history on the backend or in the dataset.
- Adding prompts to the MCP server; it currently registers tools and resources only.

## User workflow

1. Advisor opens the chat panel and chooses an installed local Ollama model.
2. Advisor asks a question or requests a draft.
3. The backend sends the prompt and available MCP tool schemas to local Ollama only.
4. When requested by the model, the backend invokes the corresponding MCP tool or reads an advertised MCP resource, then returns that result to Ollama.
5. The assistant replies with record evidence, limitations, or an unsent draft and identifies MCP tools used.
6. The advisor can continue the conversation or copy a draft. Nothing is sent or saved to a dealership record.

## Data and source of truth

- Inputs: User text, short browser-held message history, selected local model name.
- Authoritative source: MCP tool/resource results from the same validated synthetic dataset as the existing app.
- Missing/stale/conflicting-data behavior: Unknown records and insufficient evidence are reported as such. No record attributes, intervals, or repairs are guessed.
- Data retained or emitted: Chat messages remain in browser memory; MCP results are sent to the local Ollama service and returned to the browser. No remote endpoint is allowed.

## Safety, privacy, and approval

- Potential harm if wrong: Fabricated maintenance advice or a draft presented as an approved repair recommendation can reduce trust.
- Required human review: Advisors verify all record evidence and drafts. Safety items remain verification prompts.
- External actions and access: Chat requests go to loopback Ollama only. MCP tools/resources are read-only; drafts are unsent. No external service is called.

## Failure cases

- Ollama is not running or its local API is unavailable.
- No model is installed or the selected model is no longer installed.
- Model does not return tool calls reliably.
- MCP tool fails, returns no match, or reports incomplete/conflicting data.
- Model exceeds the bounded number of tool-call rounds.

## Acceptance criteria

1. Chat panel lists only models returned by the local Ollama `/api/tags` endpoint.
2. Chat requests go only to `127.0.0.1:11434`; no remote model URL, cloud fallback, or model download path exists.
3. The agent discovers and can call every registered MCP tool without maintaining a second hard-coded tool list.
4. The agent can read every fixed MCP resource and each resource template using the registered MCP client.
5. A user can complete multi-step tasks (for example, search, retrieve the selected record, then prepare a draft) in one conversation.
6. Vehicle details, recommendation status, evidence, and drafts are grounded in MCP results; unknown/incomplete/conflicting data is described as uncertain.
7. Drafts are returned as text only and cannot be sent, submitted, booked, or persisted by the chat.
8. Ollama or MCP errors produce a clear message while the existing vehicle UI remains usable.
9. Tool execution has a bounded round count and rejects model-requested tool names not discovered from the MCP server.
10. Conversation history is not persisted by the backend or written to project data.
11. Chat requests to Ollama set `think: false`.
12. A local model timeout returns HTTP 504 with a timeout message; an unreachable Ollama returns HTTP 503; neither returns a generic HTTP 500.
13. Off-topic requests (general knowledge, coding, math, etc.) receive the fixed dealership-service refusal; the model's off-topic text is never shown, and in-scope tool-grounded replies are unchanged.

## Verification plan

- Automated checks: `backend/tests/test_local_agent.py` covers timeout and connection-failure mapping, unwrapping of Ollama errors raised inside the MCP client, the `think: false` request payload, a grounded MCP tool round-trip against a fake Supabase store, and the 503/504 chat API responses (issue #18), plus the topic guardrail: scope text in the system prompt, marker refusal, hidden off-topic text, and marker after tool use (issue #24).
- Manual review: Verify local model discovery, an MCP search/retrieve flow, resource reading, draft creation, unknown serial handling, and Ollama-down handling when local services are available.
- Security/data-boundary review: Inspect all model request URLs and tool dispatch; confirm loopback-only inference, no arbitrary URL, no tools outside the MCP registry except the read-only resource reader, and no MCP writes.

## Implementation plan

1. Update the main spec and link this feature spec.
2. Add local Ollama discovery and a bounded agent loop using the existing MCP server.
3. Add chat API routes and a responsive in-app chat panel.
4. Update architecture, run/setup guide, folder tree, and file descriptions.
5. Update memory and open a review PR.

## Open questions

- None for the local synthetic demo.

## Technical references

- Ollama local chat and function tools: https://docs.ollama.com/api/chat and https://docs.ollama.com/capabilities/tool-calling
- MCP Python SDK 2.3 client for in-process servers, tools, and resources: https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0/docs/client
