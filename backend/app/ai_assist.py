"""Local-Ollama customer drafts and validated AI-suggested service items.

Both features make a single loopback Ollama call and never write records. AI suggestions
are validated here so that every displayed item cites recorded service history, states no
price or interval, and does not duplicate a stored demo recommendation.
See docs/feature-spec-local-ai-assist.md.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from .local_agent import OllamaRequestError, _ollama_request, list_local_models
from .mcp_server import create_customer_draft

DraftType = Literal["explanation", "quote", "followup"]

MAX_SUGGESTIONS = 3
AI_STATUS = "AI suggestion — unverified"

PRICE_PATTERN = re.compile(
    r"[$€£₹]|\b(?:usd|pkr|eur|gbp|dollars?|rupees?|euros?|pounds)\b|\brs\.?\s*\d",
    re.IGNORECASE,
)
INTERVAL_PATTERN = re.compile(
    r"\b\d[\d,.]*\s*(?:k\b|mi\b|miles?\b|km\b|kms\b|kilomet\w*|months?\b|years?\b|weeks?\b|days?\b)"
    r"|\bevery\s+(?:\d|other|few|several|month|year|week)",
    re.IGNORECASE,
)
SAFETY_PATTERN = re.compile(
    r"brake|tire|tyre|steering|suspension|airbag|seat ?belt|recall|headlight|tail ?light|"
    r"\blights?\b|\blamps?\b|leak|wiper",
    re.IGNORECASE,
)

SUGGESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                    "history_refs": {"type": "array", "items": {"type": "integer"}},
                    "safety_related": {"type": "boolean"},
                },
                "required": ["name", "reason", "history_refs", "safety_related"],
            },
        }
    },
    "required": ["suggestions"],
}


def _vehicle_name(vehicle: dict[str, Any]) -> str:
    return f"{vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}"


def _mileage_text(vehicle: dict[str, Any]) -> str:
    mileage = vehicle.get("mileage")
    return "not recorded" if mileage is None else f"{mileage:,} mi"


def _record_facts(vehicle: dict[str, Any]) -> str:
    """Plain-text record facts for the prompt. Telemetry is deliberately excluded."""
    lines = [
        f"Vehicle: {_vehicle_name(vehicle)} (serial {vehicle.get('serial')})",
        f"Recorded mileage: {_mileage_text(vehicle)} ({vehicle.get('mileageDate', 'date unknown')})",
        f"Record completeness: {vehicle.get('completeness', 'unknown')}",
        "Service history (numbered):",
    ]
    history = vehicle.get("history") or []
    if history:
        for number, event in enumerate(history, start=1):
            lines.append(
                f"  {number}. {event.get('date')}: {event.get('name')} — {event.get('detail')} at {event.get('mileage')}"
            )
    else:
        lines.append("  (none recorded)")
    lines.append("Stored demo recommendations:")
    recs = vehicle.get("recs") or []
    if recs:
        for rec in recs:
            lines.append(
                f"  - {rec.get('name')} [{rec.get('status')}] Evidence: {rec.get('evidence')} Rule: {rec.get('rule')}"
            )
    else:
        lines.append("  (none)")
    return "\n".join(lines)


async def _ensure_installed(model: str) -> None:
    if model not in await asyncio.to_thread(list_local_models):
        raise OllamaRequestError(
            "That model is not installed in local Ollama. Select an installed model and try again."
        )


async def _chat_once(model: str, system: str, user: str, response_format: Any = None) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2},
    }
    if response_format is not None:
        payload["format"] = response_format
    response = await asyncio.to_thread(_ollama_request, "/api/chat", payload)
    message = response.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise OllamaRequestError("The local model returned an empty response. Try again.")
    return content.strip()


DRAFT_SYSTEM_PROMPT = (
    "You write short customer-facing drafts for a dealership service advisor. Use only the record facts "
    "provided. Never state prices, costs, labor times, or maintenance intervals. Never diagnose a fault; "
    "safety-related items must be described as something the advisor will verify. Do not mention simulated "
    "telemetry. If mileage or history is missing, incomplete, or conflicting, say the advisor is confirming it. "
    "Keep the vehicle name and serial exactly as given. Return only the draft text, with no preamble."
)

DRAFT_INSTRUCTIONS = {
    "explanation": "Write a friendly explanation for the customer of what may be due or coming up and why.",
    "quote": (
        "Write a draft quote layout for advisor review listing the suggested line items. Leave every price "
        "as '[advisor to add approved pricing]'."
    ),
    "followup": "Write a brief, friendly follow-up message inviting the customer to discuss the items.",
}


async def generate_ai_draft(model: str, vehicle: dict[str, Any], draft_type: DraftType) -> dict[str, Any]:
    """Rewrite the record's template draft with the local model. Nothing is sent or stored."""
    await _ensure_installed(model)
    template = create_customer_draft(vehicle["serial"], draft_type).get("draft_text", "")
    user_prompt = (
        f"{_record_facts(vehicle)}\n\nTemplate draft to improve:\n{template}\n\n"
        f"Task: {DRAFT_INSTRUCTIONS[draft_type]} End by noting that the advisor will review the details."
    )
    text = await _chat_once(model, DRAFT_SYSTEM_PROMPT, user_prompt)
    # The quote placeholder intentionally mentions pricing without an amount; only reject real prices.
    if PRICE_PATTERN.search(text):
        raise OllamaRequestError(
            "The local model's draft included a price, which this demo does not allow. "
            "Generate again or keep the template draft."
        )
    return {
        "serial": vehicle["serial"],
        "draft_type": draft_type,
        "draft_text": text,
        "model": model,
        "source": "local_ollama",
        "synthetic_data": True,
        "sent": False,
        "requires_advisor_review": True,
    }


SUGGESTION_SYSTEM_PROMPT = (
    "You help a dealership service advisor decide what else to check during the visit, beyond the stored demo "
    "recommendations. Suggest up to 3 items an advisor commonly checks (for example cabin or engine air filter, "
    "battery test, wiper blades, fluid levels, or a related inspection) that are NOT stored recommendations "
    "and are either absent from the numbered service history or related to a recorded service. In the reason, "
    "explain what the history shows, such as 'no record of this item in the recorded visits'. In history_refs, "
    "cite the numbers of the history entries your reason relies on (for an item with no record, cite the "
    "recorded visits you reviewed). Never state prices, costs, or maintenance intervals (no distances or time "
    "periods), and do not repeat mileage numbers; the cited entries are shown to the advisor automatically. "
    "Never diagnose a fault; phrase safety-related items as something to verify. Respond only with JSON."
)


def _limitation(vehicle: dict[str, Any]) -> str | None:
    if not vehicle.get("history"):
        return "No service history is recorded, so AI suggestions cannot cite evidence."
    if vehicle.get("mileage") is None:
        return "Recorded mileage is missing. Verify mileage before requesting AI suggestions."
    if vehicle.get("conflicting"):
        return "Recorded mileage conflicts with service history. Resolve the conflict before requesting AI suggestions."
    if vehicle.get("incomplete"):
        return "The record is incomplete. Verify mileage and service history before requesting AI suggestions."
    return None


def _recorded_mileages(vehicle: dict[str, Any]) -> set[str]:
    """Digit strings of mileages actually in the record (current reading and history)."""
    values = {str(vehicle["mileage"])} if isinstance(vehicle.get("mileage"), int) else set()
    for event in vehicle.get("history") or []:
        digits = re.sub(r"\D", "", str(event.get("mileage", "")))
        if digits:
            values.add(digits)
    return values


def _without_recorded_mileages(text: str, recorded: set[str]) -> str:
    """Remove citations of recorded readings so only model-stated intervals are checked."""

    def replace(match: re.Match[str]) -> str:
        return "" if re.sub(r"\D", "", match.group(1)) in recorded else match.group(0)

    return re.sub(r"(\d[\d,]*)\s*(?:mi\b|miles?\b|km\b)", replace, text, flags=re.IGNORECASE)


def _normalized(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    return " ".join(words.split())


def _is_duplicate(name: str, existing: list[str]) -> bool:
    candidate = _normalized(name)
    return any(
        candidate == other or (len(other) >= 4 and other in candidate) or (len(candidate) >= 4 and candidate in other)
        for other in existing
        if other
    )


def validate_suggestions(raw: Any, vehicle: dict[str, Any], model: str) -> tuple[list[dict[str, Any]], int]:
    """Keep only grounded, price-free, interval-free, non-duplicate suggestions."""
    items = raw.get("suggestions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise OllamaRequestError("The local model returned suggestions in an unexpected format. Try again.")

    history = vehicle.get("history") or []
    known_names = [_normalized(str(rec.get("name", ""))) for rec in vehicle.get("recs") or []]
    recorded = _recorded_mileages(vehicle)
    accepted: list[dict[str, Any]] = []
    dropped = 0

    for item in items:
        if len(accepted) >= MAX_SUGGESTIONS:
            dropped += 1
            continue
        if not isinstance(item, dict):
            dropped += 1
            continue
        name = str(item.get("name", "")).strip()[:80]
        reason = str(item.get("reason", "")).strip()[:400]
        refs = item.get("history_refs")
        valid_refs = (
            isinstance(refs, list)
            and refs
            and all(isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= len(history) for ref in refs)
        )
        text = f"{name} {reason}"
        if (
            not name
            or not reason
            or not valid_refs
            or PRICE_PATTERN.search(text)
            or INTERVAL_PATTERN.search(_without_recorded_mileages(text, recorded))
            or _is_duplicate(name, known_names)
        ):
            dropped += 1
            continue

        cited = [history[ref - 1] for ref in dict.fromkeys(refs)]
        evidence = " · ".join(
            f"{event.get('date')}: {event.get('name')} at {event.get('mileage')}" for event in cited
        )
        evidence += f" · Current recorded mileage {_mileage_text(vehicle)}"
        safety = bool(item.get("safety_related")) or bool(SAFETY_PATTERN.search(text))
        accepted.append(
            {
                "name": name,
                "status": AI_STATUS,
                "kind": "ai",
                "text": reason,
                "evidence": evidence,
                "rule": f"Suggested by local model {model}. Not from the demo schedule; advisor must verify.",
                "safety": safety,
            }
        )
        known_names.append(_normalized(name))

    return accepted, dropped


async def generate_ai_suggestions(model: str, vehicle: dict[str, Any]) -> dict[str, Any]:
    """Ask the local model for extra service items and return only validated ones."""
    base = {
        "serial": vehicle["serial"],
        "model": model,
        "source": "local_ollama",
        "synthetic_data": True,
        "persisted": False,
    }
    limitation = _limitation(vehicle)
    if limitation:
        return {**base, "suggestions": [], "dropped": 0, "limitation": limitation}

    await _ensure_installed(model)
    content = await _chat_once(
        model,
        SUGGESTION_SYSTEM_PROMPT,
        _record_facts(vehicle),
        response_format=SUGGESTION_SCHEMA,
    )
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaRequestError("The local model returned suggestions that were not valid JSON. Try again.") from exc
    suggestions, dropped = validate_suggestions(raw, vehicle, model)
    return {**base, "suggestions": suggestions, "dropped": dropped, "limitation": None}
