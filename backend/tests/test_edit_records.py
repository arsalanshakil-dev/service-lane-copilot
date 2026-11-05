"""Checks for adding vehicles and editing records with a change log (issue #42)."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.data_store import CHANGE_LOG_LIMIT, append_change
from app.main import (
    HistoryEntryUpdate,
    NewVehicle,
    RecommendationInput,
    RecommendationUpdate,
    VehicleDetailsUpdate,
    add_vehicle,
    add_vehicle_recommendation,
    edit_history_entry,
    edit_vehicle_details,
    edit_vehicle_recommendation,
    remove_vehicle_recommendation,
    update_manual_mileage,
    ManualMileageUpdate,
)
from test_obd_telemetry import FakeSupabase

SERIAL = "NS-0001"
RECORD: dict[str, Any] = {
    "serial": SERIAL, "make": "Demo", "model": "Sedan", "year": 2021,
    "mileage": 48120, "mileageDate": "Recorded today", "completeness": "Complete demo record",
    "history": [
        {"date": "Apr 18, 2026", "name": "Engine oil and filter", "detail": "Routine service", "mileage": "39,820 mi"},
        {"date": "Nov 02, 2025", "name": "Tire rotation", "detail": "All four tires rotated", "mileage": "34,910 mi"},
    ],
    "recs": [
        {"name": "Engine oil and filter", "status": "Due", "kind": "due", "text": "t", "evidence": "e", "rule": "r", "safety": False},
    ],
    "incomplete": False, "conflicting": False,
}


def assert_http(test: unittest.TestCase, status: int, call: Any) -> None:
    with test.assertRaises(HTTPException) as caught:
        call()
    test.assertEqual(caught.exception.status_code, status, caught.exception.detail)


class EditRecordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeSupabase([{"serial": SERIAL, "record": copy.deepcopy(RECORD)}])
        self.patcher = patch("app.data_store.get_supabase_client", return_value=self.client)
        self.edits_patcher = patch("app.record_edits.get_supabase_client", return_value=self.client)
        self.patcher.start()
        self.edits_patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.edits_patcher.stop()

    def stored(self, serial: str = SERIAL) -> dict[str, Any]:
        return self.client.rows[serial]["record"]

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.client.rows)

    # ---- Add vehicle ----

    def test_add_vehicle_creates_new_record_with_paused_recommendations_and_log(self) -> None:
        created = add_vehicle(NewVehicle(serial=" new-car-1 ", make="Ironvale", model="Forge", year=2024,
                                         mileage=1200, mileageDate=date.today().isoformat()))
        stored = self.stored("NEW-CAR-1")
        self.assertEqual(created, stored)
        self.assertEqual(stored["serial"], "NEW-CAR-1")
        self.assertEqual((stored["history"], stored["recs"]), ([], []))
        self.assertTrue(stored["incomplete"])
        self.assertEqual(stored["mileage"], 1200)
        self.assertEqual(stored["changeLog"][-1]["action"], "vehicle_created")
        self.assertEqual(stored["changeLog"][-1]["actor"], "advisor (web app)")

    def test_add_vehicle_rejects_duplicates_and_invalid_input_without_writing(self) -> None:
        before = self.snapshot()
        assert_http(self, 409, lambda: add_vehicle(NewVehicle(serial="ns-0001", make="A", model="B", year=2020)))
        assert_http(self, 422, lambda: add_vehicle(NewVehicle(serial="BAD SERIAL!", make="A", model="B", year=2020)))
        assert_http(self, 422, lambda: add_vehicle(NewVehicle(serial="OK-1", make="A", model="B", year=date.today().year + 2)))
        assert_http(self, 422, lambda: add_vehicle(NewVehicle(serial="OK-2", make="A", model="B", year=2020, mileage=5)))
        self.assertEqual(self.client.rows, before)
        for bad in ({"serial": "AB"}, {"make": ""}, {"year": 1970}, {"mileage": -1}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    NewVehicle(**{"serial": "OK-3", "make": "A", "model": "B", "year": 2020, **bad})

    def test_new_vehicle_becomes_usable_after_first_recorded_service(self) -> None:
        from app.main import CompletedServiceRecord, record_service
        add_vehicle(NewVehicle(serial="NEW-CAR-2", make="Ironvale", model="Forge", year=2024))
        record_service("NEW-CAR-2", CompletedServiceRecord(serviceName="Engine oil and filter", serviceDate=date.today().isoformat(), mileage=1500))
        stored = self.stored("NEW-CAR-2")
        self.assertFalse(stored["incomplete"])
        self.assertEqual(stored["completeness"], "Advisor-entered record")
        self.assertEqual(stored["mileage"], 1500)
        self.assertEqual([e["action"] for e in stored["changeLog"]], ["vehicle_created", "service_recorded"])

    # ---- Vehicle details ----

    def test_edit_details_updates_fields_and_logs_changes(self) -> None:
        result = edit_vehicle_details(SERIAL, VehicleDetailsUpdate(make="Demo", model="Wagon", year=2022))
        self.assertEqual((result["model"], result["year"]), ("Wagon", 2022))
        self.assertIn("model 'Sedan' → 'Wagon'", self.stored()["changeLog"][-1]["summary"])

    def test_rename_moves_record_and_rejects_existing_target(self) -> None:
        self.client.rows["NS-0002"] = {"serial": "NS-0002", "record": {**copy.deepcopy(RECORD), "serial": "NS-0002"}}
        before = self.snapshot()
        assert_http(self, 409, lambda: edit_vehicle_details(SERIAL, VehicleDetailsUpdate(make="Demo", model="Sedan", year=2021, newSerial="ns-0002")))
        self.assertEqual(self.client.rows, before)
        renamed = edit_vehicle_details(SERIAL, VehicleDetailsUpdate(make="Demo", model="Sedan", year=2021, newSerial="ns-0099"))
        self.assertEqual(renamed["serial"], "NS-0099")
        self.assertNotIn(SERIAL, self.client.rows)
        self.assertEqual(self.stored("NS-0099")["history"], RECORD["history"])
        self.assertIn("serial 'NS-0001' → 'NS-0099'", self.stored("NS-0099")["changeLog"][-1]["summary"])

    def test_unknown_serial_returns_404(self) -> None:
        assert_http(self, 404, lambda: edit_vehicle_details("NOPE-1", VehicleDetailsUpdate(make="A", model="B", year=2020)))
        assert_http(self, 404, lambda: edit_history_entry("NOPE-1", 0, self.history_update()))
        assert_http(self, 404, lambda: add_vehicle_recommendation("NOPE-1", RecommendationInput(name="X", status="Due", text="t", evidence="e")))

    # ---- History ----

    def history_update(self, **overrides: Any) -> HistoryEntryUpdate:
        body = {"expected": {"date": "Nov 02, 2025", "name": "Tire rotation"}, "serviceDate": "2025-11-03",
                "name": "Tire rotation and balance", "detail": "Corrected entry", "mileage": 34950}
        body.update(overrides)
        return HistoryEntryUpdate(**body)

    def test_edit_history_entry_replaces_it_keeps_order_and_logs(self) -> None:
        result = edit_history_entry(SERIAL, 1, self.history_update())
        entry = result["history"][1]
        self.assertEqual((entry["date"], entry["name"], entry["mileage"]), ("Nov 03, 2025", "Tire rotation and balance", "34,950 mi"))
        self.assertTrue(entry["edited"])
        self.assertEqual(self.stored()["changeLog"][-1]["action"], "history_entry_updated")

    def test_moving_a_history_date_reorders_newest_first(self) -> None:
        result = edit_history_entry(SERIAL, 1, self.history_update(serviceDate="2026-05-01", mileage=40500))
        self.assertEqual([e["date"] for e in result["history"]], ["May 01, 2026", "Apr 18, 2026"])

    def test_stale_or_missing_history_entry_returns_409_without_writing(self) -> None:
        before = self.snapshot()
        assert_http(self, 409, lambda: edit_history_entry(SERIAL, 1, self.history_update(expected={"date": "Nov 02, 2025", "name": "Wrong"})))
        assert_http(self, 409, lambda: edit_history_entry(SERIAL, 9, self.history_update()))
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert_http(self, 422, lambda: edit_history_entry(SERIAL, 1, self.history_update(serviceDate=tomorrow)))
        self.assertEqual(self.client.rows, before)

    def test_history_edit_above_current_mileage_marks_conflict(self) -> None:
        conflict = edit_history_entry(SERIAL, 1, self.history_update(mileage=60000))
        self.assertTrue(conflict["conflicting"])

    def test_service_history_cannot_be_deleted_via_api_or_mcp(self) -> None:
        # User decision 2026-11-06: history can be corrected but never deleted.
        import asyncio

        from mcp import Client

        from app.main import app
        from app.mcp_server import mcp_server

        history_routes = [r for r in app.routes if getattr(r, "path", "") == "/api/vehicles/{serial}/history/{index}"]
        self.assertEqual({m for r in history_routes for m in r.methods}, {"PUT"})

        async def tool_names() -> set[str]:
            async with Client(mcp_server) as client:
                return {tool.name for tool in (await client.list_tools()).tools}

        self.assertNotIn("delete_history_entry", asyncio.run(tool_names()))

    # ---- Recommendations ----

    def test_add_edit_remove_recommendation_marks_advisor_entered_and_logs(self) -> None:
        added = add_vehicle_recommendation(SERIAL, RecommendationInput(
            name="Cabin air filter", status="Coming up", text="Advisor noted a dusty filter.", evidence="Visual check today."))
        rec = added["recs"][-1]
        self.assertEqual((rec["source"], rec["kind"], rec["status"]), ("advisor_entered", "soon", "Coming up"))
        self.assertIn("Advisor-entered", rec["rule"])
        edited = edit_vehicle_recommendation(SERIAL, 1, RecommendationUpdate(
            expectedName="Cabin air filter", name="Cabin air filter", status="Due", text="Replace now.", evidence="Visual check today.", safety=False))
        self.assertEqual(edited["recs"][1]["kind"], "due")
        removed = remove_vehicle_recommendation(SERIAL, 1, "Cabin air filter")
        self.assertEqual([r["name"] for r in removed["recs"]], ["Engine oil and filter"])
        actions = [entry["action"] for entry in self.stored()["changeLog"]]
        self.assertEqual(actions[-3:], ["recommendation_added", "recommendation_updated", "recommendation_removed"])

    def test_recommendation_conflicts_and_validation(self) -> None:
        before = self.snapshot()
        assert_http(self, 409, lambda: add_vehicle_recommendation(SERIAL, RecommendationInput(
            name="engine oil and filter", status="Due", text="t", evidence="e")))
        assert_http(self, 409, lambda: remove_vehicle_recommendation(SERIAL, 0, "Wrong name"))
        assert_http(self, 409, lambda: edit_vehicle_recommendation(SERIAL, 5, RecommendationUpdate(
            expectedName="x", name="x", status="Due", text="t", evidence="e")))
        self.assertEqual(self.client.rows, before)
        with self.assertRaises(ValidationError):
            RecommendationInput(name="X", status="Overdue", text="t", evidence="e")
        with self.assertRaises(ValidationError):
            RecommendationInput(name="X", status="Due", text="", evidence="e")

    # ---- Change log ----

    def test_existing_mileage_route_now_logs(self) -> None:
        update_manual_mileage(SERIAL, ManualMileageUpdate(mileage=48500, mileageDate=date.today().isoformat(), mileageSource="advisor_observed"))
        self.assertEqual(self.stored()["changeLog"][-1]["action"], "mileage_updated")

    def test_change_log_keeps_latest_100(self) -> None:
        record: dict[str, Any] = {}
        for number in range(CHANGE_LOG_LIMIT + 7):
            append_change(record, "test", f"entry {number}")
        self.assertEqual(len(record["changeLog"]), CHANGE_LOG_LIMIT)
        self.assertEqual(record["changeLog"][-1]["summary"], f"entry {CHANGE_LOG_LIMIT + 6}")
        self.assertEqual(record["changeLog"][0]["summary"], "entry 7")


if __name__ == "__main__":
    unittest.main()
