"""Checks for editable maintenance rules and computed recommendations (issue #47)."""

from __future__ import annotations

import isolation  # noqa: F401  (must run before app imports)

import asyncio
import copy
import unittest
from datetime import date
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from mcp import Client

from app.main import (
    CompletedServiceRecord,
    RuleInput,
    RuleUpdate,
    create_rule,
    edit_rule,
    get_vehicle,
    list_rules,
    record_service,
    search_vehicles,
)
from app.mcp_server import mcp_server
from app.rules_engine import compute_rule_recommendations
from test_obd_telemetry import FakeSupabase


def rule(rule_id: str, name: str, soon: int, due: int, safety: bool = False, enabled: bool = True) -> dict[str, Any]:
    return {"id": rule_id, "service_name": name, "coming_up_miles": soon, "due_miles": due, "safety": safety,
            "enabled": enabled, "change_log": [], "updated_at": "2026-11-06T00:00:00+00:00"}


RULES = [
    rule("engine-oil-and-filter", "Engine oil and filter", 4000, 5000),
    rule("tire-rotation", "Tire rotation", 6000, 7500),
    rule("brake-inspection", "Brake inspection", 12000, 15000, safety=True),
    rule("cabin-air-filter", "Cabin air filter", 12000, 15000),
]
SERIAL = "NS-0001"
VEHICLE: dict[str, Any] = {
    "serial": SERIAL, "make": "Demo", "model": "Sedan", "year": 2021,
    "mileage": 48120, "mileageDate": "Recorded today", "completeness": "Complete demo record",
    "history": [
        {"date": "Apr 18, 2026", "name": "Engine oil and filter", "detail": "", "mileage": "39,820 mi"},  # 8,300 since → Due
        {"date": "Nov 02, 2025", "name": "Tire rotation", "detail": "", "mileage": "41,000 mi"},          # 7,120 since → Coming up
        {"date": "Dec 09, 2024", "name": "Brake inspection", "detail": "", "mileage": "24,105 mi"},       # 24,015 since → safety
    ],
    # Legacy stored recommendation (seed data) and one advisor-entered item.
    "recs": [
        {"name": "Legacy item", "status": "Due", "kind": "due", "text": "t", "evidence": "e", "rule": "old", "safety": False},
        {"name": "Wiper blades", "status": "Coming up", "kind": "soon", "text": "t", "evidence": "e", "rule": "r",
         "safety": False, "source": "advisor_entered"},
    ],
    "incomplete": False, "conflicting": False,
}


class ComputeTests(unittest.TestCase):
    def test_due_coming_up_safety_and_unrecorded_services(self) -> None:
        items = {r["name"]: r for r in compute_rule_recommendations(copy.deepcopy(VEHICLE), RULES)}
        self.assertEqual(items["Engine oil and filter"]["status"], "Due")
        self.assertIn("8,300 mi since service", items["Engine oil and filter"]["evidence"])
        self.assertIn("Demo rule: due at 5,000 mi", items["Engine oil and filter"]["rule"])
        self.assertEqual(items["Tire rotation"]["status"], "Coming up")
        self.assertEqual((items["Brake inspection"]["status"], items["Brake inspection"]["kind"]), ("Advisor verification", "safety"))
        self.assertTrue(items["Brake inspection"]["safety"])
        self.assertNotIn("Cabin air filter", items)  # never recorded → no evidence → no claim
        self.assertTrue(all(r["source"] == "rule" for r in items.values()))

    def test_not_yet_due_and_disabled_rules_produce_nothing(self) -> None:
        vehicle = copy.deepcopy(VEHICLE)
        vehicle["mileage"] = 40000  # oil 180 mi since, tire −1000 (ignored), brake 15,895 → safety
        names = {r["name"] for r in compute_rule_recommendations(vehicle, RULES)}
        self.assertEqual(names, {"Brake inspection"})
        disabled = [dict(r, enabled=False) for r in RULES]
        self.assertEqual(compute_rule_recommendations(copy.deepcopy(VEHICLE), disabled), [])

    def test_paused_for_incomplete_conflicting_or_missing_mileage(self) -> None:
        for changes in ({"incomplete": True}, {"conflicting": True}, {"mileage": None}):
            with self.subTest(changes=changes):
                self.assertEqual(compute_rule_recommendations({**copy.deepcopy(VEHICLE), **changes}, RULES), [])

    def test_latest_matching_entry_is_used_and_unreadable_mileage_is_skipped(self) -> None:
        vehicle = copy.deepcopy(VEHICLE)
        vehicle["history"].insert(0, {"date": "Nov 01, 2026", "name": "Engine oil and filter", "detail": "", "mileage": "48,000 mi"})
        names = {r["name"] for r in compute_rule_recommendations(vehicle, RULES)}
        self.assertNotIn("Engine oil and filter", names)  # just done
        vehicle["history"][0]["mileage"] = "—"
        self.assertNotIn("Engine oil and filter", {r["name"] for r in compute_rule_recommendations(vehicle, RULES)})


class StoreCase(unittest.TestCase):
    rules: list[dict[str, Any]] | None = RULES

    def setUp(self) -> None:
        self.client = FakeSupabase([{"serial": SERIAL, "record": copy.deepcopy(VEHICLE)}], rules=self.rules)
        self.patchers = [patch(f"app.{m}.get_supabase_client", return_value=self.client) for m in ("data_store", "record_edits")]
        for p in self.patchers:
            p.start()

    def tearDown(self) -> None:
        for p in self.patchers:
            p.stop()


class EffectiveRecordTests(StoreCase):
    def test_vehicle_api_shows_rule_items_plus_advisor_items_and_drops_legacy(self) -> None:
        shown = get_vehicle(SERIAL)
        self.assertEqual(shown["rulesStatus"], "active")
        names = [r["name"] for r in shown["recs"]]
        self.assertEqual(names, ["Engine oil and filter", "Brake inspection", "Tire rotation", "Wiper blades"])  # Due, verify, Coming up, advisor
        self.assertNotIn("Legacy item", names)
        advisor = shown["recs"][-1]
        self.assertEqual((advisor["source"], advisor["index"]), ("advisor_entered", 1))
        # Stored data is untouched.
        self.assertEqual(self.client.rows[SERIAL]["record"]["recs"], VEHICLE["recs"])

    def test_records_list_counts_effective_open_items(self) -> None:
        summary = search_vehicles(q=SERIAL, limit=5, offset=0)["vehicles"][0]
        self.assertEqual(summary["open_recommendations"], 4)  # 3 rule items + advisor Coming up

    def test_mark_as_done_on_rule_item_records_service_and_item_disappears(self) -> None:
        result = record_service(SERIAL, CompletedServiceRecord(serviceName="Engine oil and filter", serviceDate=date.today().isoformat(),
                                                               mileage=48120, recommendationName="Engine oil and filter"))
        self.assertNotIn("Engine oil and filter", [r["name"] for r in result["recs"]])
        self.assertEqual(self.client.rows[SERIAL]["record"]["history"][0]["name"], "Engine oil and filter")

    def test_changing_a_rule_changes_status_on_next_read(self) -> None:
        rule_row = next(r for r in list_rules()["rules"] if r["id"] == "engine-oil-and-filter")
        edit_rule("engine-oil-and-filter", RuleUpdate(expectedUpdatedAt=rule_row["updated_at"], serviceName="Engine oil and filter",
                                                      comingUpMiles=9000, dueMiles=10000, safety=False, enabled=True))
        names = [r["name"] for r in get_vehicle(SERIAL)["recs"]]
        self.assertNotIn("Engine oil and filter", names)  # 8,300 mi is now below 9,000

    def test_mcp_get_vehicle_record_returns_computed_items(self) -> None:
        async def call() -> dict[str, Any]:
            async with Client(mcp_server) as client:
                return (await client.call_tool("get_vehicle_record", {"serial": SERIAL})).structured_content

        record = asyncio.run(call())
        record = record.get("vehicle", record)
        self.assertIn("Brake inspection", [r["name"] for r in record["recs"]])


class RulesUnavailableTests(StoreCase):
    rules = None  # migration not applied

    def test_stored_recommendations_shown_with_unavailable_status(self) -> None:
        shown = get_vehicle(SERIAL)
        self.assertEqual(shown["rulesStatus"], "unavailable")
        self.assertEqual(shown["recs"], VEHICLE["recs"])
        listing = list_rules()
        self.assertEqual((listing["status"], listing["rules"]), ("unavailable", []))
        self.assertIn("20261106000100_create_service_rules.sql", listing["detail"])
        with self.assertRaises(HTTPException) as caught:
            create_rule(RuleInput(serviceName="Coolant", comingUpMiles=20000, dueMiles=30000))
        self.assertEqual(caught.exception.status_code, 503)


class RuleApiTests(StoreCase):
    def test_add_rule_validates_rejects_duplicates_and_logs(self) -> None:
        created = create_rule(RuleInput(serviceName="Coolant flush", comingUpMiles=25000, dueMiles=30000))
        self.assertEqual(created["id"], "coolant-flush")
        self.assertEqual(created["change_log"][-1]["action"], "rule_added")
        self.assertIn("coolant-flush", self.client.rules)
        for body, status in (({"serviceName": "tire ROTATION", "comingUpMiles": 1, "dueMiles": 2}, 409),
                             ({"serviceName": "Spark plugs", "comingUpMiles": 5000, "dueMiles": 5000}, 422)):
            with self.subTest(body=body):
                with self.assertRaises(HTTPException) as caught:
                    create_rule(RuleInput(**body))
                self.assertEqual(caught.exception.status_code, status)

    def test_edit_rule_logs_changes_and_rejects_stale_or_unknown(self) -> None:
        current = self.client.rules["tire-rotation"]
        updated = edit_rule("tire-rotation", RuleUpdate(expectedUpdatedAt=current["updated_at"], serviceName="Tire rotation",
                                                        comingUpMiles=5000, dueMiles=7000, safety=False, enabled=False))
        self.assertFalse(updated["enabled"])
        self.assertIn("due 7500 → 7000", updated["change_log"][-1]["summary"])
        for rule_id, expected, status in (("tire-rotation", "stale", 409), ("no-such-rule", "x", 404)):
            with self.subTest(rule_id=rule_id):
                with self.assertRaises(HTTPException) as caught:
                    edit_rule(rule_id, RuleUpdate(expectedUpdatedAt=expected, serviceName="Tire rotation", comingUpMiles=1, dueMiles=2))
                self.assertEqual(caught.exception.status_code, status)


if __name__ == "__main__":
    unittest.main()
