"""Regression checks for local AI drafts and AI-suggested service items (issue #22)."""

from __future__ import annotations

import asyncio
import copy
import json
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException

from app import ai_assist
from app.ai_assist import AI_STATUS, validate_suggestions
from app.local_agent import OllamaRequestError, OllamaTimeoutError, OllamaUnavailableError
from app.main import AiDraftRequest, AiSuggestionsRequest, ai_customer_draft, ai_service_suggestions

MODEL = "qwen3.5:4b"
VEHICLE: dict[str, Any] = {
    "serial": "NS-0001",
    "make": "Demo",
    "model": "Sedan",
    "year": 2021,
    "mileage": 48120,
    "mileageDate": "Recorded today",
    "completeness": "Complete demo record",
    "history": [
        {"date": "Apr 18, 2026", "name": "Engine oil and filter", "detail": "Routine service", "mileage": "39,820 mi"},
        {"date": "Nov 02, 2025", "name": "Tire rotation", "detail": "All four tires rotated", "mileage": "34,910 mi"},
        {"date": "Dec 09, 2024", "name": "Brake inspection", "detail": "Inspection completed", "mileage": "24,105 mi"},
    ],
    "recs": [
        {"name": "Engine oil and filter", "status": "Due", "kind": "due", "text": "t", "evidence": "e", "rule": "r", "safety": False},
        {"name": "Tire rotation", "status": "Coming up", "kind": "soon", "text": "t", "evidence": "e", "rule": "r", "safety": False},
    ],
    "obdTelemetry": {"mode": "simulated", "notice": "SIMULATED-TELEMETRY-MARKER", "streams": []},
}


def suggestion(name: str, reason: str, refs: list[Any], safety: bool = False, interval: Any = 0) -> dict[str, Any]:
    return {
        "name": name,
        "reason": reason,
        "history_refs": refs,
        "safety_related": safety,
        "typical_interval_miles": interval,
    }


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class SuggestionValidationTests(unittest.TestCase):
    def validate(self, *items: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        return validate_suggestions({"suggestions": list(items)}, VEHICLE, MODEL)

    def test_grounded_suggestion_gets_backend_built_evidence_and_ai_label(self) -> None:
        accepted, dropped = self.validate(
            suggestion("Cabin air filter check", "Not listed in the recorded history; worth confirming.", [1, 2])
        )
        self.assertEqual(dropped, 0)
        self.assertEqual(len(accepted), 1)
        item = accepted[0]
        self.assertEqual(item["status"], AI_STATUS)
        self.assertEqual(item["kind"], "ai")
        self.assertIn("Apr 18, 2026: Engine oil and filter at 39,820 mi", item["evidence"])
        self.assertIn("Nov 02, 2025: Tire rotation at 34,910 mi", item["evidence"])
        self.assertIn("Current recorded mileage 48,120 mi", item["evidence"])
        self.assertIn(MODEL, item["rule"])
        self.assertIn("advisor must verify", item["rule"])

    def test_invalid_history_references_are_dropped(self) -> None:
        accepted, dropped = self.validate(
            suggestion("Cabin air filter", "Reason", []),
            suggestion("Wheel alignment check", "Reason", [9]),
            suggestion("Battery test", "Reason", [0]),
            suggestion("Coolant check", "Reason", ["1"]),
            suggestion("Spark plugs", "Reason", [True]),
        )
        self.assertEqual(accepted, [])
        self.assertEqual(dropped, 5)

    def test_prices_are_still_dropped(self) -> None:
        accepted, dropped = self.validate(
            suggestion("Battery test", "Usually costs $45.", [1]),
            suggestion("Wiper inspection", "About 500 PKR at most shops.", [1]),
        )
        self.assertEqual(accepted, [])
        self.assertEqual(dropped, 2)

    def test_model_interval_estimate_is_allowed_and_labelled_unverified(self) -> None:
        # Issue #30: stated intervals are no longer dropped; they are shown as a model estimate.
        accepted, dropped = self.validate(
            suggestion("Coolant flush", "Commonly done around 30,000 miles; no record in history.", [1], interval=30000),
        )
        self.assertEqual(dropped, 0)
        self.assertEqual(accepted[0]["interval_estimate_miles"], 30000)
        self.assertIn("Model estimate", accepted[0]["rule"])
        self.assertIn("about every 30,000 mi", accepted[0]["rule"])
        self.assertIn("Unverified", accepted[0]["rule"])

    def test_invalid_interval_estimates_are_ignored_not_shown(self) -> None:
        for bad in (0, -5, 999_999, "10000", True, None):
            with self.subTest(bad=bad):
                accepted, _ = self.validate(suggestion("Coolant flush", "No record in history.", [1], interval=bad))
                self.assertIsNone(accepted[0]["interval_estimate_miles"])
                self.assertNotIn("Model estimate", accepted[0]["rule"])

    def test_citing_a_recorded_mileage_is_not_treated_as_an_interval(self) -> None:
        accepted, dropped = self.validate(
            suggestion("Cabin air filter check", "Last full service was at 39,820 mi; confirm filter status.", [1])
        )
        self.assertEqual(dropped, 0)
        self.assertEqual(len(accepted), 1)

    def test_duplicates_of_stored_recommendations_and_each_other_are_dropped(self) -> None:
        accepted, dropped = self.validate(
            suggestion("Tire rotation", "Reason", [2]),
            suggestion("engine oil & filter", "Reason", [1]),
            suggestion("Battery test", "Reason", [1]),
            suggestion("Battery test", "Reason again", [1]),
        )
        self.assertEqual([item["name"] for item in accepted], ["Battery test"])
        self.assertEqual(dropped, 3)

    def test_at_most_three_suggestions_are_returned(self) -> None:
        names = ["Battery test", "Cabin air filter", "Wiper blades", "Coolant level check"]
        accepted, dropped = self.validate(*(suggestion(name, "Reason", [1]) for name in names))
        self.assertEqual(len(accepted), 3)
        self.assertEqual(dropped, 1)

    def test_safety_related_items_are_flagged_by_keyword_or_model(self) -> None:
        accepted, _ = self.validate(
            suggestion("Brake fluid check", "Verify brake fluid condition.", [3]),
            suggestion("Battery test", "Reason", [1], safety=True),
            suggestion("Cabin air filter", "Reason", [1]),
        )
        self.assertEqual([item["safety"] for item in accepted], [True, True, False])

    def test_unexpected_shape_raises_request_error(self) -> None:
        with self.assertRaises(OllamaRequestError):
            validate_suggestions(["not", "a", "dict"], VEHICLE, MODEL)


class RepeatGuardTests(unittest.TestCase):
    """Issue #30: never re-suggest a service the history shows was done recently."""

    TODAY = datetime(2026, 11, 5)

    def vehicle_with(self, *events: dict[str, Any], mileage: int | None = 48120) -> dict[str, Any]:
        vehicle = copy.deepcopy(VEHICLE)
        vehicle["mileage"] = mileage
        vehicle["history"] = [*events, *vehicle["history"]]
        return vehicle

    def validate(self, vehicle: dict[str, Any], *items: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        return validate_suggestions({"suggestions": list(items)}, vehicle, MODEL, today=self.TODAY)

    def test_wipers_changed_10_miles_ago_are_not_suggested_again(self) -> None:
        # The user's example: oil change + wiper change, car returns 10 miles later.
        vehicle = self.vehicle_with(
            {"date": "Nov 04, 2026", "name": "Wiper blades", "detail": "Front wipers", "mileage": "48,110 mi"},
            mileage=48120,
        )
        for name in ("Wiper blades", "Wiper blade condition check", "Windshield wiper blades", "wiper"):
            with self.subTest(name=name):
                accepted, dropped = self.validate(vehicle, suggestion(name, "Common item.", [1], interval=12000))
                self.assertEqual(accepted, [])
                self.assertEqual(dropped, 1)

    def test_floor_applies_even_when_model_gives_a_tiny_interval(self) -> None:
        vehicle = self.vehicle_with(
            {"date": "Oct 01, 2026", "name": "Wiper blades", "detail": "", "mileage": "47,500 mi"},
        )
        accepted, _ = self.validate(vehicle, suggestion("Wiper blades", "Common item.", [1], interval=5))
        self.assertEqual(accepted, [])  # 620 mi ago < 1,000 mi demo floor

    def test_item_past_its_estimated_interval_can_be_suggested(self) -> None:
        vehicle = self.vehicle_with(
            {"date": "Jan 10, 2024", "name": "Wiper blades", "detail": "", "mileage": "20,000 mi"},
        )
        accepted, dropped = self.validate(vehicle, suggestion("Wiper blades", "Last changed long ago.", [1], interval=12000))
        self.assertEqual(dropped, 0)
        self.assertEqual(accepted[0]["name"], "Wiper blades")

    def test_item_within_its_estimated_interval_is_dropped(self) -> None:
        vehicle = self.vehicle_with(
            {"date": "Mar 01, 2026", "name": "Cabin air filter", "detail": "", "mileage": "44,000 mi"},
        )
        accepted, _ = self.validate(vehicle, suggestion("Cabin air filter", "Reason.", [1], interval=15000))
        self.assertEqual(accepted, [])  # 4,120 mi ago < 15,000 mi estimate

    def test_service_without_odometer_uses_30_day_guard(self) -> None:
        recent = self.vehicle_with({"date": "Oct 25, 2026", "name": "Wiper blades", "detail": "", "mileage": "Not recorded"})
        old = self.vehicle_with({"date": "Jan 05, 2026", "name": "Wiper blades", "detail": "", "mileage": "Not recorded"})
        self.assertEqual(self.validate(recent, suggestion("Wiper blades", "Reason.", [1]))[0], [])
        self.assertEqual(len(self.validate(old, suggestion("Wiper blades", "Reason.", [1]))[0]), 1)

    def test_unrelated_service_does_not_block_a_suggestion(self) -> None:
        # "Engine oil and filter" must not block "Cabin air filter" just because both mention "filter".
        accepted, dropped = self.validate(copy.deepcopy(VEHICLE), suggestion("Cabin air filter", "Reason.", [1], interval=15000))
        self.assertEqual(dropped, 0)
        self.assertEqual(len(accepted), 1)

    def test_never_recorded_item_is_dropped_until_its_estimated_interval_is_reached(self) -> None:
        vehicle = copy.deepcopy(VEHICLE)  # 48,120 mi, no spark plug or coolant history
        accepted, dropped = self.validate(
            vehicle,
            suggestion("Spark plugs", "Commonly replaced by this mileage.", [1], interval=60000),
            suggestion("Coolant flush", "Commonly done by this mileage.", [1], interval=30000),
        )
        self.assertEqual([item["name"] for item in accepted], ["Coolant flush"])
        self.assertEqual(dropped, 1)

    def test_prompt_shows_miles_since_each_service(self) -> None:
        facts = ai_assist._record_facts(copy.deepcopy(VEHICLE))
        self.assertIn("at 39,820 mi (8,300 mi ago)", facts)
        self.assertIn("at 34,910 mi (13,210 mi ago)", facts)


class SuggestionFlowTests(unittest.TestCase):
    def test_limited_records_return_limitation_without_calling_ollama(self) -> None:
        cases = {
            "no history": {"history": []},
            "missing mileage": {"mileage": None},
            "conflicting": {"conflicting": True},
            "incomplete": {"incomplete": True},
        }
        for label, changes in cases.items():
            with self.subTest(label):
                vehicle = {**copy.deepcopy(VEHICLE), **changes}
                with patch.object(ai_assist, "_ollama_request") as ollama, patch.object(
                    ai_assist, "list_local_models"
                ) as models:
                    result = run(ai_assist.generate_ai_suggestions(MODEL, vehicle))
                ollama.assert_not_called()
                models.assert_not_called()
                self.assertEqual(result["suggestions"], [])
                self.assertTrue(result["limitation"])

    def test_prompt_excludes_telemetry_disables_thinking_and_uses_json_schema(self) -> None:
        captured: list[dict[str, Any]] = []
        model_reply = {"suggestions": [suggestion("Battery test", "Not in recorded history.", [1])]}

        def fake_ollama(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            captured.append(copy.deepcopy(payload))
            return {"message": {"role": "assistant", "content": json.dumps(model_reply)}}

        with patch.object(ai_assist, "list_local_models", return_value=[MODEL]), patch.object(
            ai_assist, "_ollama_request", side_effect=fake_ollama
        ):
            result = run(ai_assist.generate_ai_suggestions(MODEL, copy.deepcopy(VEHICLE)))

        self.assertEqual(len(captured), 1)
        payload = captured[0]
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["format"], ai_assist.SUGGESTION_SCHEMA)
        prompt = json.dumps(payload["messages"])
        self.assertNotIn("SIMULATED-TELEMETRY-MARKER", prompt)
        self.assertIn("1. Apr 18, 2026: Engine oil and filter", prompt)
        self.assertEqual([item["name"] for item in result["suggestions"]], ["Battery test"])
        self.assertFalse(result["persisted"])

    def test_non_json_model_output_is_a_request_error(self) -> None:
        with patch.object(ai_assist, "list_local_models", return_value=[MODEL]), patch.object(
            ai_assist, "_ollama_request", return_value={"message": {"content": "not json"}}
        ):
            with self.assertRaises(OllamaRequestError):
                run(ai_assist.generate_ai_suggestions(MODEL, copy.deepcopy(VEHICLE)))


class AiDraftTests(unittest.TestCase):
    def draft_with_reply(self, reply: str, draft_type: str = "explanation") -> tuple[dict[str, Any], list[dict[str, Any]]]:
        captured: list[dict[str, Any]] = []

        def fake_ollama(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            captured.append(copy.deepcopy(payload))
            return {"message": {"role": "assistant", "content": reply}}

        with patch.object(ai_assist, "list_local_models", return_value=[MODEL]), patch.object(
            ai_assist, "_ollama_request", side_effect=fake_ollama
        ), patch("app.mcp_server.find_vehicle", return_value=copy.deepcopy(VEHICLE)):
            result = run(ai_assist.generate_ai_draft(MODEL, copy.deepcopy(VEHICLE), draft_type))
        return result, captured

    def test_draft_is_unsent_model_text_grounded_in_template_without_telemetry(self) -> None:
        result, captured = self.draft_with_reply("  Hello! Your oil service may be due. Your advisor will review.  ")
        self.assertEqual(result["draft_text"], "Hello! Your oil service may be due. Your advisor will review.")
        self.assertFalse(result["sent"])
        self.assertTrue(result["requires_advisor_review"])
        payload = captured[0]
        self.assertIs(payload["think"], False)
        prompt = json.dumps(payload["messages"])
        self.assertIn("Template draft to improve", prompt)
        self.assertIn("Engine oil and filter", prompt)
        self.assertNotIn("SIMULATED-TELEMETRY-MARKER", prompt)

    def test_quote_placeholder_without_amount_is_allowed(self) -> None:
        result, _ = self.draft_with_reply("Line items: oil service — [advisor to add approved pricing]", "quote")
        self.assertIn("approved pricing", result["draft_text"])

    def test_draft_with_price_is_rejected(self) -> None:
        with self.assertRaises(OllamaRequestError):
            self.draft_with_reply("Your oil change will cost $79.99.")

    def test_empty_draft_is_rejected(self) -> None:
        with self.assertRaises(OllamaRequestError):
            self.draft_with_reply("   ")

    def test_uninstalled_model_is_rejected_before_generation(self) -> None:
        with patch.object(ai_assist, "list_local_models", return_value=["other:1b"]), patch.object(
            ai_assist, "_ollama_request"
        ) as ollama:
            with self.assertRaises(OllamaRequestError):
                run(ai_assist.generate_ai_draft(MODEL, copy.deepcopy(VEHICLE), "explanation"))
        ollama.assert_not_called()


class AiRouteTests(unittest.TestCase):
    def test_unknown_serial_returns_404_without_calling_ollama(self) -> None:
        with patch("app.main.find_vehicle", return_value=None), patch.object(ai_assist, "_ollama_request") as ollama:
            for call in (
                ai_customer_draft("NOPE-1", AiDraftRequest(model=MODEL, draftType="quote")),
                ai_service_suggestions("NOPE-1", AiSuggestionsRequest(model=MODEL)),
            ):
                with self.assertRaises(HTTPException) as caught:
                    run(call)
                self.assertEqual(caught.exception.status_code, 404)
        ollama.assert_not_called()

    def test_ollama_errors_map_to_504_503_502(self) -> None:
        cases = [
            (OllamaTimeoutError("did not respond within 600 seconds"), 504),
            (OllamaUnavailableError("down"), 503),
            (OllamaRequestError("bad output"), 502),
        ]
        for error, status in cases:
            with self.subTest(status=status):
                with patch("app.main.find_vehicle", return_value=copy.deepcopy(VEHICLE)), patch(
                    "app.main.generate_ai_suggestions", side_effect=error
                ), patch("app.main.generate_ai_draft", side_effect=error):
                    for call in (
                        ai_service_suggestions("NS-0001", AiSuggestionsRequest(model=MODEL)),
                        ai_customer_draft("NS-0001", AiDraftRequest(model=MODEL, draftType="explanation")),
                    ):
                        with self.assertRaises(HTTPException) as caught:
                            run(call)
                        self.assertEqual(caught.exception.status_code, status)

    def test_routes_never_write_to_the_vehicle_store(self) -> None:
        reply = {"message": {"content": json.dumps({"suggestions": []})}}
        with patch("app.main.find_vehicle", return_value=copy.deepcopy(VEHICLE)), patch(
            "app.main.update_vehicle_mileage"
        ) as write, patch("app.data_store.update_vehicle_mileage") as store_write, patch.object(
            ai_assist, "list_local_models", return_value=[MODEL]
        ), patch.object(ai_assist, "_ollama_request", return_value=reply):
            result = run(ai_service_suggestions("NS-0001", AiSuggestionsRequest(model=MODEL)))
        write.assert_not_called()
        store_write.assert_not_called()
        self.assertEqual(result["suggestions"], [])
        self.assertEqual(result["dropped"], 0)


if __name__ == "__main__":
    unittest.main()
