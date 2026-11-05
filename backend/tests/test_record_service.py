"""Regression checks for recording completed services (issue #28)."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import data_store
from app.main import CompletedServiceRecord, record_service
from app.mcp_server import mcp_server
from test_obd_telemetry import FakeSupabase

SERIAL = "NS-0001"
RECORD: dict[str, Any] = {
    "serial": SERIAL,
    "make": "Demo",
    "model": "Sedan",
    "year": 2021,
    "mileage": 48120,
    "mileageDate": "Recorded today",
    "completeness": "Complete demo record",
    "history": [
        {"date": "Apr 18, 2026", "name": "Engine oil and filter", "detail": "Routine service", "mileage": "39,820 mi"},
        {"date": "Nov 02, 2025", "name": "Tire rotation", "detail": "All four tires rotated", "mileage": "34,910 mi"},
    ],
    "recs": [
        {"name": "Engine oil and filter", "status": "Due", "kind": "due", "text": "t", "evidence": "e",
         "rule": "Demo rule: due at 7,500 mi since last service.", "safety": False},
        {"name": "Tire rotation", "status": "Coming up", "kind": "soon", "text": "t", "evidence": "e",
         "rule": "r", "safety": False},
    ],
}


def payload(**overrides: Any) -> CompletedServiceRecord:
    body: dict[str, Any] = {
        "serviceName": "Engine oil and filter",
        "serviceDate": "2026-05-01",
        "mileage": 48200,
        "detail": "Synthetic oil",
        "recommendationName": "Engine oil and filter",
    }
    body.update(overrides)
    return CompletedServiceRecord(**body)


class RecordServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeSupabase([{"serial": SERIAL, "record": copy.deepcopy(RECORD)}])
        self.patcher = patch("app.data_store.get_supabase_client", return_value=self.client)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def stored(self) -> dict[str, Any]:
        return self.client.rows[SERIAL]["record"]

    def test_completing_a_recommendation_persists_history_status_and_mileage(self) -> None:
        returned = record_service(SERIAL, payload())
        stored = self.stored()
        self.assertEqual(returned, stored)

        newest = stored["history"][0]
        self.assertEqual(newest["date"], "May 01, 2026")
        self.assertEqual(newest["name"], "Engine oil and filter")
        self.assertEqual(newest["mileage"], "48,200 mi")
        self.assertEqual(newest["detail"], "Synthetic oil")
        self.assertEqual(newest["source"], "advisor_recorded")
        self.assertEqual(len(stored["history"]), 3)

        oil, rotation = stored["recs"]
        self.assertEqual(oil["status"], "Completed")
        self.assertEqual(oil["kind"], "done")
        self.assertIn("May 01, 2026", oil["evidence"])
        self.assertIn("48,200 mi", oil["evidence"])
        self.assertEqual(oil["rule"], RECORD["recs"][0]["rule"])
        self.assertEqual(rotation, RECORD["recs"][1])

        self.assertEqual(stored["mileage"], 48200)
        self.assertEqual(stored["mileageDate"], "2026-05-01")
        self.assertEqual(stored["mileageSource"], "advisor_observed")
        self.assertFalse(stored["conflicting"])

        # A later lookup reads the saved record back from the store.
        self.assertEqual(data_store.find_vehicle(SERIAL)["recs"][0]["status"], "Completed")

    def test_other_service_without_recommendation_only_adds_history(self) -> None:
        record_service(SERIAL, payload(serviceName="Wiper blades", recommendationName=None, mileage=48125))
        stored = self.stored()
        self.assertEqual(stored["history"][0]["name"], "Wiper blades")
        self.assertEqual(stored["recs"], RECORD["recs"])

    def test_history_is_kept_newest_first_for_a_backdated_service(self) -> None:
        record_service(SERIAL, payload(serviceDate="2025-12-15", recommendationName=None, mileage=36000))
        self.assertEqual(
            [event["date"] for event in self.stored()["history"]],
            ["Apr 18, 2026", "Dec 15, 2025", "Nov 02, 2025"],
        )

    def test_lower_or_missing_odometer_leaves_current_mileage_unchanged(self) -> None:
        for mileage in (40000, None):
            with self.subTest(mileage=mileage):
                self.setUp()
                record_service(SERIAL, payload(mileage=mileage, recommendationName=None))
                stored = self.stored()
                self.assertEqual(stored["mileage"], 48120)
                self.assertEqual(stored["mileageDate"], "Recorded today")
                expected = "Not recorded" if mileage is None else "40,000 mi"
                self.assertEqual(stored["history"][0]["mileage"], expected)
                self.tearDown()

    def test_unknown_serial_returns_404_without_writing(self) -> None:
        before = copy.deepcopy(self.client.rows)
        with self.assertRaises(HTTPException) as caught:
            record_service("NOPE-1", payload())
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.client.rows, before)

    def test_unknown_recommendation_and_future_date_return_422_without_writing(self) -> None:
        before = copy.deepcopy(self.client.rows)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        for body in (payload(recommendationName="Timing belt"), payload(serviceDate=tomorrow)):
            with self.subTest(body=body):
                with self.assertRaises(HTTPException) as caught:
                    record_service(SERIAL, body)
                self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.client.rows, before)

    def test_invalid_payloads_are_rejected_by_validation(self) -> None:
        invalid = [
            {"serviceName": "   "},
            {"serviceName": "x" * 81},
            {"mileage": -1},
            {"mileage": 1.5},
            {"detail": "x" * 201},
            {"serviceDate": "not-a-date"},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    payload(**overrides)

    def test_mcp_record_service_tool_writes_and_logs_mcp_agent(self) -> None:
        # Issue #44 deliberately added MCP write tools; they reuse this validated write path.
        import asyncio

        from mcp import Client

        async def call() -> dict[str, Any]:
            async with Client(mcp_server) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertIn("record_completed_service", names)
                result = await client.call_tool("record_completed_service", {
                    "serial": SERIAL, "service_name": "Wiper blades", "service_date": "2026-05-01", "mileage": 48200,
                })
                return result.structured_content

        result = asyncio.run(call())
        self.assertTrue(result["saved"])
        self.assertEqual(self.stored()["history"][0]["name"], "Wiper blades")
        self.assertEqual(self.stored()["changeLog"][-1]["actor"], "MCP agent")


if __name__ == "__main__":
    unittest.main()
