"""Checks for the per-vehicle AI summary (issue #38)."""

from __future__ import annotations

import asyncio
import copy
import json
import unittest
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException

from app import ai_assist
from app.local_agent import OllamaRequestError, OllamaTimeoutError, OllamaUnavailableError
from app.main import AiSuggestionsRequest, ai_vehicle_summary

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
        {"date": "Dec 09, 2024", "name": "Brake inspection", "detail": "Inspection completed", "mileage": "24,105 mi"},
    ],
    "recs": [
        {"name": "Engine oil and filter", "status": "Due", "kind": "due", "text": "t", "evidence": "8,300 mi since service", "rule": "r", "safety": False},
        {"name": "Brake system inspection", "status": "Advisor verification", "kind": "safety", "text": "t", "evidence": "e", "rule": "r", "safety": True},
        {"name": "Tire rotation", "status": "Completed", "kind": "done", "text": "t", "evidence": "e", "rule": "r", "safety": False},
    ],
    "obdTelemetry": {"mode": "simulated", "notice": "SIMULATED-TELEMETRY-MARKER", "streams": []},
}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class AiSummaryTests(unittest.TestCase):
    def summarize(self, reply: str, vehicle: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        captured: list[dict[str, Any]] = []

        def fake_ollama(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            captured.append(copy.deepcopy(payload))
            return {"message": {"role": "assistant", "content": reply}}

        with patch.object(ai_assist, "list_local_models", return_value=[MODEL]), patch.object(
            ai_assist, "_ollama_request", side_effect=fake_ollama
        ):
            result = run(ai_assist.generate_ai_summary(MODEL, copy.deepcopy(vehicle or VEHICLE)))
        return result, captured

    def test_summary_is_grounded_unsent_and_lists_structured_open_items(self) -> None:
        result, captured = self.summarize("- Oil service is Due (8,300 mi since service).\n- Verify brake inspection timing.")
        self.assertTrue(result["summary"].startswith("- Oil service is Due"))
        self.assertEqual(
            result["open_items"],
            [{"name": "Engine oil and filter", "status": "Due", "safety": False},
             {"name": "Brake system inspection", "status": "Advisor verification", "safety": True}],
        )
        self.assertIsNone(result["limitation"])
        self.assertFalse(result["persisted"])
        # "Needs now" is built by the backend from stored recommendations, never from model text.
        self.assertEqual(
            result["needs_now"],
            ["Engine oil and filter: Due — 8,300 mi since service",
             "Brake system inspection: Advisor verification — e"],
        )
        payload = captured[0]
        self.assertIs(payload["think"], False)
        prompt = json.dumps(payload["messages"])
        self.assertIn("Engine oil and filter [Due]", prompt)
        self.assertNotIn("SIMULATED-TELEMETRY-MARKER", prompt)
        self.assertIn("Never state prices", payload["messages"][0]["content"])
        self.assertIn("do NOT restate", payload["messages"][0]["content"])

    def test_needs_now_reports_nothing_open(self) -> None:
        vehicle = {**copy.deepcopy(VEHICLE), "recs": [VEHICLE["recs"][2]]}  # only a Completed item
        result, _ = self.summarize("- Recent tire rotation recorded.", vehicle)
        self.assertEqual(result["needs_now"], ["No stored recommendation is Due, Coming up, or awaiting advisor verification."])
        self.assertEqual(result["open_items"], [])

    def test_incomplete_record_passes_limitation_to_model_and_response(self) -> None:
        vehicle = {**copy.deepcopy(VEHICLE), "mileage": None, "incomplete": True}
        result, captured = self.summarize("- Mileage is missing; verify before relying on this.", vehicle)
        self.assertIn("missing", result["limitation"].lower())
        self.assertIn("before relying on this summary", result["limitation"])
        self.assertIn("Data limitation:", captured[0]["messages"][1]["content"])

    def test_summary_with_price_is_rejected(self) -> None:
        with self.assertRaises(OllamaRequestError):
            self.summarize("- Oil service will cost $79.")

    def test_empty_summary_is_rejected(self) -> None:
        with self.assertRaises(OllamaRequestError):
            self.summarize("   ")

    def test_uninstalled_model_is_rejected_before_generation(self) -> None:
        with patch.object(ai_assist, "list_local_models", return_value=["other:1b"]), patch.object(
            ai_assist, "_ollama_request"
        ) as ollama:
            with self.assertRaises(OllamaRequestError):
                run(ai_assist.generate_ai_summary(MODEL, copy.deepcopy(VEHICLE)))
        ollama.assert_not_called()


class AiSummaryRouteTests(unittest.TestCase):
    def test_unknown_serial_returns_404_without_calling_ollama(self) -> None:
        with patch("app.main.find_vehicle", return_value=None), patch.object(ai_assist, "_ollama_request") as ollama:
            with self.assertRaises(HTTPException) as caught:
                run(ai_vehicle_summary("NOPE-1", AiSuggestionsRequest(model=MODEL)))
        self.assertEqual(caught.exception.status_code, 404)
        ollama.assert_not_called()

    def test_ollama_errors_map_to_504_503_502(self) -> None:
        for error, status in ((OllamaTimeoutError("slow"), 504), (OllamaUnavailableError("down"), 503), (OllamaRequestError("bad"), 502)):
            with self.subTest(status=status):
                with patch("app.main.find_vehicle", return_value=copy.deepcopy(VEHICLE)), patch(
                    "app.main.generate_ai_summary", side_effect=error
                ):
                    with self.assertRaises(HTTPException) as caught:
                        run(ai_vehicle_summary("NS-0001", AiSuggestionsRequest(model=MODEL)))
                self.assertEqual(caught.exception.status_code, status)

    def test_route_never_writes(self) -> None:
        reply = {"message": {"content": "- Nothing is due."}}
        with patch("app.main.find_vehicle", return_value=copy.deepcopy(VEHICLE)), patch(
            "app.data_store.update_vehicle_mileage"
        ) as mileage_write, patch("app.data_store.record_completed_service") as service_write, patch.object(
            ai_assist, "list_local_models", return_value=[MODEL]
        ), patch.object(ai_assist, "_ollama_request", return_value=reply):
            result = run(ai_vehicle_summary("NS-0001", AiSuggestionsRequest(model=MODEL)))
        mileage_write.assert_not_called()
        service_write.assert_not_called()
        self.assertEqual(result["summary"], "- Nothing is due.")


if __name__ == "__main__":
    unittest.main()
