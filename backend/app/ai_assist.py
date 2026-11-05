"""Local-Ollama customer drafts and validated AI-suggested service items.

Both features make a single loopback Ollama call and never write records. AI suggestions
are validated here so that every displayed item cites recorded service history, states no
price, does not duplicate a stored demo recommendation, and is not repeated too soon after a
recorded service. The model may give its own typical-interval estimate, which is shown as an
unverified model estimate (approved AGENTS.md exception, issue #30).
See docs/feature-spec-local-ai-assist.md.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
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
# Demo repeat guard (issue #30): never re-suggest a service recorded fewer miles ago than this,
# whatever interval the model estimates; fall back to days when the odometer was not recorded.
REPEAT_FLOOR_MILES = 1_000
REPEAT_FLOOR_DAYS = 30
MAX_INTERVAL_MILES = 200_000
# Generic words ignored when matching a suggestion to a recorded service ("Wiper blade check" ~ "Wiper blades").
GENERIC_SERVICE_WORDS = {
    "and", "the", "of", "for", "check", "checks", "inspection", "inspect", "service", "services",
    "replacement", "replace", "change", "condition", "verification", "verify", "test", "level",
    "levels", "system", "routine", "new",
}
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
                    "typical_interval_miles": {"type": "integer"},
                },
                "required": ["name", "reason", "history_refs", "safety_related", "typical_interval_miles"],
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


def _event_miles(event: dict[str, Any]) -> int | None:
    digits = re.sub(r"\D", "", str(event.get("mileage", "")))
    return int(digits) if digits else None


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
        current = vehicle.get("mileage")
        for number, event in enumerate(history, start=1):
            event_miles = _event_miles(event)
            since = (
                f" ({current - event_miles:,} mi ago)"
                if isinstance(current, int) and event_miles is not None and current >= event_miles
                else ""
            )
            lines.append(
                f"  {number}. {event.get('date')}: {event.get('name')} — {event.get('detail')} at {event.get('mileage')}{since}"
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
    "You help a dealership service advisor decide what else to check during this visit, based on the "
    "vehicle's current mileage and how many miles ago each service was last done. Using your general "
    "maintenance knowledge, suggest up to 3 items commonly due at this mileage (for example cabin or engine "
    "air filter, battery test, wiper blades, coolant, brake fluid, spark plugs, transmission fluid, or a "
    "related inspection) that are NOT stored recommendations. Do not suggest an item that the history shows "
    "was done recently compared with its typical interval. In typical_interval_miles give your estimate of "
    "the usual interval in miles for that item (0 if it is not mileage-based); it is shown to the advisor as "
    "an unverified estimate. In the reason, explain it from the mileage and history, for example 'no record "
    "of this item; commonly checked by this mileage'. In history_refs cite the history entry numbers your "
    "reason relies on (for an item never recorded, cite the recorded visits you reviewed). Never state "
    "prices or costs. Never diagnose a fault; phrase safety-related items as something to verify. "
    "Respond only with JSON."
)


def _limitation(vehicle: dict[str, Any], purpose: str = "requesting AI suggestions") -> str | None:
    if not vehicle.get("history"):
        return "No service history is recorded, so AI output cannot cite evidence."
    if vehicle.get("mileage") is None:
        return f"Recorded mileage is missing. Verify mileage before {purpose}."
    if vehicle.get("conflicting"):
        return f"Recorded mileage conflicts with service history. Resolve the conflict before {purpose}."
    if vehicle.get("incomplete"):
        return f"The record is incomplete. Verify mileage and service history before {purpose}."
    return None


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


def _service_keywords(name: str) -> set[str]:
    words = {word.rstrip("s") if len(word) > 3 else word for word in _normalized(name).split()}
    return {word for word in words if word and word not in GENERIC_SERVICE_WORDS}


def _matches_service(suggestion_name: str, event_name: str) -> bool:
    """True when a suggestion names the same service as a recorded history event."""
    suggestion, event = _service_keywords(suggestion_name), _service_keywords(event_name)
    if not suggestion or not event:
        return False
    return suggestion <= event or event <= suggestion


def _interval_estimate(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_INTERVAL_MILES:
        return value
    return None


def _done_too_recently(name: str, interval: int | None, vehicle: dict[str, Any], today: datetime) -> bool:
    """True when the item is not due yet by mileage: a matching recorded service is inside the
    repeat guard, or (never recorded) the vehicle has not reached the model's interval estimate."""
    current = vehicle.get("mileage")
    threshold = max(interval or 0, REPEAT_FLOOR_MILES)
    matching = [event for event in vehicle.get("history") or [] if _matches_service(name, str(event.get("name", "")))]
    if not matching and interval and isinstance(current, int) and current < interval:
        return True
    for event in matching:
        event_miles = _event_miles(event)
        if isinstance(current, int) and event_miles is not None:
            if current - event_miles < threshold:
                return True
            continue
        try:
            performed = datetime.strptime(str(event.get("date")), "%b %d, %Y")
        except ValueError:
            continue
        if (today - performed).days < REPEAT_FLOOR_DAYS:
            return True
    return False


def validate_suggestions(
    raw: Any,
    vehicle: dict[str, Any],
    model: str,
    today: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Keep only grounded, price-free, non-duplicate suggestions that were not done too recently."""
    today = today or datetime.now()
    items = raw.get("suggestions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise OllamaRequestError("The local model returned suggestions in an unexpected format. Try again.")

    history = vehicle.get("history") or []
    known_names = [_normalized(str(rec.get("name", ""))) for rec in vehicle.get("recs") or []]
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
        interval = _interval_estimate(item.get("typical_interval_miles"))
        if (
            not name
            or not reason
            or not valid_refs
            or PRICE_PATTERN.search(text)
            or _is_duplicate(name, known_names)
            or _done_too_recently(name, interval, vehicle, today)
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
                "rule": (
                    f"Model estimate ({model}): about every {interval:,} mi. Unverified; check the manufacturer schedule."
                    if interval
                    else f"Suggested by local model {model}. Not from the demo schedule; advisor must verify."
                ),
                "interval_estimate_miles": interval,
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


# ---- Per-vehicle AI summary for the Vehicle records view (issue #38) ----

SUMMARY_OPEN_STATUSES = ("Due", "Coming up", "Advisor verification")

SUMMARY_SYSTEM_PROMPT = (
    "You add context to a dealership service advisor's quick overview of one vehicle record. What the car "
    "needs now is already shown to the advisor from the stored recommendations, so do NOT restate due, "
    "coming-up, or advisor-verification items, their mileage, or their rules. Write 2 or 3 short bullet "
    "points, each starting with '- ', about: notable recent services in the history (with dates), "
    "safety-related items the advisor should verify, and any data limitation (start with it if there is "
    "one and say the advisor must verify before relying on the overview). Use only the record facts given. "
    "Never state prices or costs, maintenance intervals, or diagnoses, and do not mention simulated "
    "telemetry. Return only the bullet points."
)


def _needs_now(vehicle: dict[str, Any]) -> list[str]:
    """Backend-built, exact 'needs now' lines from stored recommendations (never model text)."""
    lines = [
        f"{rec.get('name')}: {rec.get('status')} — {rec.get('evidence')}"
        for rec in vehicle.get("recs") or []
        if rec.get("status") in SUMMARY_OPEN_STATUSES
    ]
    return lines or ["No stored recommendation is Due, Coming up, or awaiting advisor verification."]


def _open_items(vehicle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"name": rec.get("name"), "status": rec.get("status"), "safety": bool(rec.get("safety"))}
        for rec in vehicle.get("recs") or []
        if rec.get("status") in SUMMARY_OPEN_STATUSES
    ]


async def generate_ai_summary(model: str, vehicle: dict[str, Any]) -> dict[str, Any]:
    """Summarize what one vehicle needs, from the stored record only. Nothing is written."""
    await _ensure_installed(model)
    limitation = _limitation(vehicle, purpose="relying on this summary")
    user_prompt = _record_facts(vehicle)
    if limitation:
        user_prompt += f"\nData limitation: {limitation}"
    text = await _chat_once(model, SUMMARY_SYSTEM_PROMPT, user_prompt)
    if PRICE_PATTERN.search(text):
        raise OllamaRequestError(
            "The local model's summary included a price, which this demo does not allow. Try again."
        )
    return {
        "serial": vehicle["serial"],
        "model": model,
        "needs_now": _needs_now(vehicle),
        "summary": text,
        "open_items": _open_items(vehicle),
        "limitation": limitation,
        "source": "local_ollama",
        "synthetic_data": True,
        "persisted": False,
    }
