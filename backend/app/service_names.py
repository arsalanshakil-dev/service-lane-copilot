"""Service-name matching shared by AI suggestions and the maintenance rules engine.

Names are compared by keywords, ignoring generic words, so "Wiper blade check" matches
"Wiper blades" but "Cabin air filter" does not match "Engine oil and filter".
"""

from __future__ import annotations

import re

# Generic words ignored when matching a suggestion to a recorded service ("Wiper blade check" ~ "Wiper blades").
GENERIC_SERVICE_WORDS = {
    "and", "the", "of", "for", "check", "checks", "inspection", "inspect", "service", "services",
    "replacement", "replace", "change", "condition", "verification", "verify", "test", "level",
    "levels", "system", "routine", "new",
}


def normalized_name(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    return " ".join(words.split())


def service_keywords(name: str) -> set[str]:
    words = {word.rstrip("s") if len(word) > 3 else word for word in normalized_name(name).split()}
    return {word for word in words if word and word not in GENERIC_SERVICE_WORDS}


def matches_service(suggestion_name: str, event_name: str) -> bool:
    """True when a suggestion names the same service as a recorded history event."""
    suggestion, event = service_keywords(suggestion_name), service_keywords(event_name)
    if not suggestion or not event:
        return False
    return suggestion <= event or event <= suggestion
