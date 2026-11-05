"""Local Ollama chat orchestration over the app's registered MCP capabilities."""

import asyncio
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp import Client

from .mcp_server import mcp_server

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_TIMEOUT_SECONDS = 180
MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_LENGTH = 4_000
MAX_TOOL_RESULT_LENGTH = 24_000
RESOURCE_TOOL_NAME = "read_mcp_resource"


class OllamaUnavailableError(RuntimeError):
    """The local Ollama service could not be reached."""


class OllamaRequestError(RuntimeError):
    """Ollama returned an error for a local model request."""


def _ollama_request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a JSON request to the fixed loopback Ollama service."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{OLLAMA_BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1_000]
        raise OllamaRequestError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OllamaUnavailableError(
            "Could not reach the local Ollama service at 127.0.0.1:11434."
        ) from exc
    if not isinstance(result, dict):
        raise OllamaRequestError("Ollama returned an invalid response.")
    return result


def list_local_models() -> list[str]:
    """Return model names reported by the local Ollama installation."""
    result = _ollama_request("/api/tags")
    models = result.get("models", [])
    if not isinstance(models, list):
        raise OllamaRequestError("Ollama returned an invalid model list.")
    return sorted(
        {
            model["name"]
            for model in models
            if isinstance(model, dict) and isinstance(model.get("name"), str)
        }
    )


def _content_text(blocks: list[Any]) -> str:
    parts = []
    for block in blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            uri = getattr(block, "uri", None)
            if isinstance(uri, str):
                parts.append(f"Resource: {uri}")
    return "\n".join(parts)


def _tool_result_text(result: Any) -> str:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        content = json.dumps(structured, ensure_ascii=False, default=str)
    else:
        content = _content_text(getattr(result, "content", []))
    if getattr(result, "is_error", False):
        content = f"MCP tool error: {content or 'The tool returned an error.'}"
    return content[:MAX_TOOL_RESULT_LENGTH]


def _resource_read_tool(resource_description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": RESOURCE_TOOL_NAME,
            "description": (
                "Read one of the MCP server's advertised read-only resources. "
                f"Available resources: {resource_description}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "uri": {
                        "type": "string",
                        "description": "An exact advertised resource URI or a URI matching an advertised template.",
                    }
                },
                "required": ["uri"],
            },
        },
    }


def _resource_uri_allowed(uri: str, fixed_uris: set[str], templates: list[str]) -> bool:
    if uri in fixed_uris:
        return True
    for template in templates:
        pattern = re.escape(template)
        pattern = "^" + "[^/]+".join(re.escape(part) for part in re.split(r"\{[^{}]+\}", template)) + "$"
        if re.fullmatch(pattern, uri):
            return True
    return False


def _resource_result_text(result: Any) -> str:
    parts = []
    for item in getattr(result, "contents", []):
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif getattr(item, "mimeType", None):
            parts.append(f"[Non-text MCP resource: {item.mimeType}]")
        else:
            parts.append("[Non-text MCP resource content]")
    return "\n".join(parts)[:MAX_TOOL_RESULT_LENGTH]


def _tool_definitions(tools: list[Any], resource_description: str) -> list[dict[str, Any]]:
    definitions = []
    for tool in tools:
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.name,
                    "parameters": tool.input_schema,
                },
            }
        )
    if resource_description:
        if any(item["function"]["name"] == RESOURCE_TOOL_NAME for item in definitions):
            raise OllamaRequestError("MCP tool name conflicts with the resource reader.")
        definitions.append(_resource_read_tool(resource_description))
    return definitions


def _tool_call_parts(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = call.get("function", {})
    if not isinstance(function, dict):
        return "", {}
    name = function.get("name", "")
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return "", {}
    return name, arguments


async def chat_with_local_agent(
    model: str,
    message: str,
    history: list[dict[str, str]],
) -> dict[str, Any]:
    """Run a bounded local model conversation with all registered MCP tools/resources."""
    local_models = await asyncio.to_thread(list_local_models)
    if model not in local_models:
        raise OllamaRequestError(
            "That model is not installed in local Ollama. Select an installed model and try again."
        )

    safe_history = [
        {"role": turn["role"], "content": turn["content"][:MAX_MESSAGE_LENGTH]}
        for turn in history[-MAX_HISTORY_MESSAGES:]
        if turn.get("role") in {"user", "assistant"}
        and isinstance(turn.get("content"), str)
    ]
    safe_history.append({"role": "user", "content": message[:MAX_MESSAGE_LENGTH]})

    system_prompt = (
        "You are Service Lane Copilot, a local assistant for dealership service advisors. "
        "Use only the provided MCP tool and resource results for vehicle records, service history, "
        "recommendation status, evidence, and drafts. Do not invent vehicle facts, mileage, service "
        "intervals, prices, or repairs. If records are unknown, incomplete, stale, or conflicting, "
        "state what is missing and keep the result uncertain. Treat safety-related items as prompts "
        "for advisor verification, never as diagnoses. Drafts are editable text only and are never sent. "
        "You cannot modify records, book service, contact anyone, access a vehicle, or call outside services. "
        "When you discuss a service suggestion, include its recorded status and evidence when available."
    )

    tools_used: list[str] = []
    async with Client(mcp_server) as client:
        tool_result = await client.list_tools()
        resources_result = await client.list_resources()
        templates_result = await client.list_resource_templates()
        fixed_uris = {
            str(resource.uri)
            for resource in getattr(resources_result, "resources", [])
            if isinstance(getattr(resource, "uri", None), str)
        }
        resource_templates = [
            str(resource.uri_template)
            for resource in getattr(templates_result, "resource_templates", [])
            if isinstance(getattr(resource, "uri_template", None), str)
        ]
        resource_description = ", ".join(
            [*sorted(fixed_uris), *resource_templates]
        )
        tool_definitions = _tool_definitions(
            getattr(tool_result, "tools", []), resource_description
        )
        tool_names = {
            item["function"]["name"]
            for item in tool_definitions
            if item["function"]["name"] != RESOURCE_TOOL_NAME
        }

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *safe_history,
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            response = await asyncio.to_thread(
                _ollama_request,
                "/api/chat",
                {
                    "model": model,
                    "messages": messages,
                    "tools": tool_definitions,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            assistant_message = response.get("message")
            if not isinstance(assistant_message, dict):
                raise OllamaRequestError("Ollama returned no assistant message.")
            messages.append(assistant_message)
            calls = assistant_message.get("tool_calls", [])
            if not isinstance(calls, list) or not calls:
                return {
                    "reply": str(assistant_message.get("content", "")).strip(),
                    "tools_used": list(dict.fromkeys(tools_used)),
                    "model": model,
                }

            for call in calls:
                if not isinstance(call, dict):
                    continue
                name, arguments = _tool_call_parts(call)
                if name == RESOURCE_TOOL_NAME:
                    uri = arguments.get("uri")
                    if not isinstance(uri, str) or not _resource_uri_allowed(
                        uri, fixed_uris, resource_templates
                    ):
                        result_text = "Resource read denied: URI is not advertised by this MCP server."
                    else:
                        try:
                            resource_result = await client.read_resource(uri)
                            result_text = _resource_result_text(resource_result)
                        except Exception:
                            result_text = "MCP resource read failed. Report that the requested resource was unavailable."
                    tools_used.append(RESOURCE_TOOL_NAME)
                    messages.append(
                        {"role": "tool", "tool_name": name, "content": result_text}
                    )
                elif name in tool_names:
                    try:
                        result = await client.call_tool(name, arguments)
                        result_text = _tool_result_text(result)
                    except Exception:
                        result_text = "MCP tool call failed. Report that the requested record operation was unavailable."
                    tools_used.append(name)
                    messages.append(
                        {"role": "tool", "tool_name": name, "content": result_text}
                    )
                else:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": name or "unknown",
                            "content": "Tool call denied: the requested tool is not registered on this MCP server.",
                        }
                    )

        return {
            "reply": (
                "I reached the safe limit for MCP steps in this turn. "
                "Try asking for one vehicle or one draft at a time."
            ),
            "tools_used": list(dict.fromkeys(tools_used)),
            "model": model,
        }
