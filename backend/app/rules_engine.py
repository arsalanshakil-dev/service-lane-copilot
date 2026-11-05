"""Editable demo maintenance rules and computed recommendations (issue #47).

Rules live in `public.service_rules`. Recommendations are computed on every read from a
record's history and current mileage, then combined with stored Advisor-entered items.
If the rules table is missing or unreadable the stored recommendations are shown as before
with `rulesStatus: "unavailable"`; there is no other fallback.
See docs/spec/feature-spec-editable-rules.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import data_store
from .data_store import CHANGE_LOG_LIMIT, WEB_ACTOR
from .service_names import matches_service, normalized_name

RULES_TABLE = "service_rules"
MAX_RULE_MILES = 200_000
RULE_FIELDS = "id,service_name,coming_up_miles,due_miles,safety,enabled,change_log,updated_at"


class RulesUnavailable(RuntimeError):
    """The rules table is missing or unreadable (migration not applied, or database down)."""


class RuleConflict(Exception):
    """Duplicate service name or stale edit → HTTP 409."""


class RuleValidation(ValueError):
    """Invalid rule values → HTTP 422."""


# ---- Loading rules ----

def load_rules() -> list[dict[str, Any]]:
    try:
        result = data_store.get_supabase_client().table(RULES_TABLE).select(RULE_FIELDS).order("service_name").execute()
    except Exception as exc:
        raise RulesUnavailable(
            "Maintenance rules are not set up. Apply supabase/migrations/20261106000100_create_service_rules.sql "
            "(see README) to enable rule-computed recommendations."
        ) from exc
    rows = getattr(result, "data", None)
    if not isinstance(rows, list):
        raise RulesUnavailable("The rules table returned an invalid response.")
    return [row for row in rows if isinstance(row, dict)]


def try_load_rules() -> list[dict[str, Any]] | None:
    try:
        return load_rules()
    except RulesUnavailable:
        return None


# ---- Computing recommendations ----

def _miles(value: Any) -> int | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def compute_rule_recommendations(vehicle: dict[str, Any], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rule items for one vehicle. Paused (empty) for incomplete, conflicting, or no-mileage records."""
    current = vehicle.get("mileage")
    if not isinstance(current, int) or vehicle.get("incomplete") or vehicle.get("conflicting"):
        return []
    items = []
    for rule in rules:
        if not rule.get("enabled"):
            continue
        name = str(rule.get("service_name", ""))
        latest = next((e for e in vehicle.get("history") or [] if matches_service(name, str(e.get("name", "")))), None)
        last_miles = _miles(latest.get("mileage")) if latest else None
        if latest is None or last_miles is None or last_miles > current:
            continue  # no evidence → no claim
        since = current - last_miles
        due, soon = int(rule["due_miles"]), int(rule["coming_up_miles"])
        if since < soon:
            continue
        safety = bool(rule.get("safety"))
        if safety:
            status, kind = "Advisor verification", "safety"
            text = f"{name} is in the demo rule's review range. This is a verification prompt, not a diagnosis."
        elif since >= due:
            status, kind = "Due", "due"
            text = f"The demo rule interval has been reached since the last recorded {name.lower()}."
        else:
            status, kind = "Coming up", "soon"
            text = f"The demo rule places {name.lower()} in the coming-up range."
        items.append({
            "name": name,
            "status": status,
            "kind": kind,
            "text": text,
            "evidence": (f"Last recorded at {last_miles:,} mi ({latest.get('date')}) · "
                         f"Current recorded mileage {current:,} mi · {since:,} mi since service"),
            "rule": f"Demo rule: due at {due:,} mi since last service; coming up from {soon:,} mi.",
            "safety": safety,
            "source": "rule",
            "ruleId": rule.get("id"),
        })
    # Most urgent first: Due, then safety verification, then Coming up; ties by name.
    priority = {"Due": 0, "Advisor verification": 1, "Coming up": 2}
    return sorted(items, key=lambda item: (priority[item["status"]], item["name"].lower()))


def effective_vehicle(vehicle: dict[str, Any] | None, rules: list[dict[str, Any]] | None = None, *, load: bool = True) -> dict[str, Any] | None:
    """The record as shown: rule items + stored Advisor-entered items (with their stored `index`).

    `rules=None` with `load=True` loads rules from the database. If rules are unavailable the
    stored recommendations are returned unchanged with `rulesStatus: "unavailable"`.
    """
    if vehicle is None:
        return None
    if rules is None and load:
        rules = try_load_rules()
    shown = dict(vehicle)
    if rules is None:
        shown["rulesStatus"] = "unavailable"
        return shown
    advisor = [
        {**rec, "index": position}
        for position, rec in enumerate(vehicle.get("recs") or [])
        if rec.get("source") == "advisor_entered"
    ]
    shown["recs"] = compute_rule_recommendations(vehicle, rules) + advisor
    shown["rulesStatus"] = "active"
    return shown


def rule_recommendation_names(vehicle: dict[str, Any]) -> set[str]:
    """Names of rule items currently shown for a vehicle (accepted by "Mark as done")."""
    rules = try_load_rules()
    if rules is None:
        return set()
    return {rec["name"] for rec in compute_rule_recommendations(vehicle, rules)}


# ---- Editing rules ----

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "rule"


def _validate(service_name: str, coming_up: int, due: int) -> str:
    name = " ".join(service_name.split())
    if not 1 <= len(name) <= 80:
        raise RuleValidation("Service name must be 1–80 characters.")
    if not (0 <= coming_up < due <= MAX_RULE_MILES):
        raise RuleValidation(f"Use 0 ≤ coming-up miles < due miles ≤ {MAX_RULE_MILES:,}.")
    return name


def _log(rule: dict[str, Any], action: str, summary: str, actor: str) -> list[dict[str, Any]]:
    log = list(rule.get("change_log") or [])
    log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action, "actor": actor, "summary": summary})
    return log[-CHANGE_LOG_LIMIT:]


def _ensure_unique(name: str, rules: list[dict[str, Any]], except_id: str | None = None) -> None:
    key = normalized_name(name)
    if any(normalized_name(str(r.get("service_name", ""))) == key and r.get("id") != except_id for r in rules):
        raise RuleConflict(f"A rule for '{name}' already exists.")


def add_rule(service_name: str, coming_up_miles: int, due_miles: int, safety: bool, actor: str = WEB_ACTOR) -> dict[str, Any]:
    name = _validate(service_name, coming_up_miles, due_miles)
    rules = load_rules()
    _ensure_unique(name, rules)
    rule_id, suffix = _slug(name), 2
    existing_ids = {r.get("id") for r in rules}
    while rule_id in existing_ids:
        rule_id, suffix = f"{_slug(name)}-{suffix}", suffix + 1
    row = {
        "id": rule_id, "service_name": name, "coming_up_miles": coming_up_miles, "due_miles": due_miles,
        "safety": safety, "enabled": True, "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    row["change_log"] = _log({}, "rule_added", f"Added rule '{name}': coming up from {coming_up_miles:,} mi, due at {due_miles:,} mi{', safety' if safety else ''}.", actor)
    try:
        data_store.get_supabase_client().table(RULES_TABLE).insert(row).execute()
    except Exception as exc:
        raise RulesUnavailable("The rule could not be saved. Check the database and the rules migration.") from exc
    return row


def update_rule(
    rule_id: str, expected_updated_at: str, service_name: str, coming_up_miles: int, due_miles: int,
    safety: bool, enabled: bool, actor: str = WEB_ACTOR,
) -> dict[str, Any] | None:
    name = _validate(service_name, coming_up_miles, due_miles)
    rules = load_rules()
    current = next((r for r in rules if r.get("id") == rule_id), None)
    if current is None:
        return None
    if str(current.get("updated_at")) != expected_updated_at:
        raise RuleConflict("That rule changed since the page loaded. Reload Settings and try again.")
    _ensure_unique(name, rules, except_id=rule_id)
    changes = [
        f"{label} {old!r} → {new!r}"
        for label, old, new in (
            ("name", current.get("service_name"), name), ("coming up", current.get("coming_up_miles"), coming_up_miles),
            ("due", current.get("due_miles"), due_miles), ("safety", current.get("safety"), safety),
            ("enabled", current.get("enabled"), enabled))
        if old != new
    ]
    if not changes:
        return current
    updated = {
        **current, "service_name": name, "coming_up_miles": coming_up_miles, "due_miles": due_miles,
        "safety": safety, "enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    updated["change_log"] = _log(current, "rule_updated", f"Changed {'; '.join(changes)}.", actor)
    payload = {k: updated[k] for k in ("service_name", "coming_up_miles", "due_miles", "safety", "enabled", "updated_at", "change_log")}
    try:
        result = data_store.get_supabase_client().table(RULES_TABLE).update(payload).eq("id", rule_id).select("id").execute()
    except Exception as exc:
        raise RulesUnavailable("The rule change could not be saved.") from exc
    if not getattr(result, "data", None):
        raise RulesUnavailable("The database did not confirm the rule change.")
    return updated
