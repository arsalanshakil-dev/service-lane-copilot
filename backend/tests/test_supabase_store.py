from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import data_store
from app.main import get_vehicle
from fastapi import HTTPException
from seed_supabase import build_seed_rows, seed_vehicles


class FakeSupabase:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.error: Exception | None = None

    def table(self, name: str) -> "FakeQuery":
        if name != data_store.VEHICLE_TABLE:
            raise AssertionError(f"Unexpected table: {name}")
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, client: FakeSupabase) -> None:
        self.client = client
        self.operation = "select"
        self.filters: dict[str, object] = {}
        self.payload: dict | list[dict] | None = None
        self.row_limit: int | None = None
        self.order_by: str | None = None

    def select(self, _columns: str) -> "FakeQuery":
        return self

    def eq(self, column: str, value: object) -> "FakeQuery":
        self.filters[column] = value
        return self

    def limit(self, count: int) -> "FakeQuery":
        self.row_limit = count
        return self

    def order(self, column: str) -> "FakeQuery":
        self.order_by = column
        return self

    def update(self, payload: dict) -> "FakeQuery":
        self.operation = "update"
        self.payload = copy.deepcopy(payload)
        return self

    def upsert(self, payload: list[dict], **_options: object) -> "FakeQuery":
        self.operation = "upsert"
        self.payload = copy.deepcopy(payload)
        return self

    def execute(self) -> SimpleNamespace:
        if self.client.error is not None:
            raise self.client.error
        if self.operation == "upsert":
            assert isinstance(self.payload, list)
            for row in self.payload:
                self.client.rows[row["serial"]] = copy.deepcopy(row)
            return SimpleNamespace(data=copy.deepcopy(self.payload))

        if self.operation == "update":
            serial = self.filters.get("serial")
            if not isinstance(serial, str) or serial not in self.client.rows:
                return SimpleNamespace(data=[])
            assert isinstance(self.payload, dict)
            self.client.rows[serial].update(copy.deepcopy(self.payload))
            return SimpleNamespace(data=[{"serial": serial}])

        rows = [
            copy.deepcopy(row)
            for row in self.client.rows.values()
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.order_by:
            rows.sort(key=lambda row: row[self.order_by])
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return SimpleNamespace(data=rows)


class SupabaseVehicleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeSupabase()
        self.record = {
            "serial": "TEST-001",
            "make": "Toyota",
            "model": "Demo",
            "year": 2022,
            "mileage": 22_500,
            "mileageDate": "2026-01-01",
            "mileageSource": "customer_reported",
            "completeness": "Complete demo record",
            "incomplete": False,
            "conflicting": False,
            "history": [{"mileage": "20,000 mi", "name": "Oil service"}],
            "recs": [{"name": "Tire rotation", "status": "Coming up"}],
            "obdTelemetry": {
                "mode": "simulated",
                "streams": [{"key": "engine_rpm", "samples": [{"value": 800}]}],
            },
        }
        self.client.rows["TEST-001"] = {
            "serial": "TEST-001",
            "record": copy.deepcopy(self.record),
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        self.client_patch = patch("app.data_store.get_supabase_client", return_value=self.client)
        self.client_patch.start()

    def tearDown(self) -> None:
        self.client_patch.stop()

    def test_known_and_unknown_lookups_use_database_rows(self) -> None:
        self.assertEqual(data_store.find_vehicle(" test-001 "), self.record)
        self.assertIsNone(data_store.find_vehicle("UNKNOWN"))

    def test_rest_vehicle_lookup_reads_supabase_and_unknown_is_404(self) -> None:
        self.assertEqual(get_vehicle("TEST-001"), self.record)
        with self.assertRaises(HTTPException) as raised:
            get_vehicle("UNKNOWN")
        self.assertEqual(raised.exception.status_code, 404)

    def test_search_reads_current_records_and_returns_summaries(self) -> None:
        results = data_store.search_vehicle_summaries("toyota", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["serial"], "TEST-001")
        self.assertNotIn("history", results[0])

    def test_mileage_update_persists_and_preserves_other_record_fields(self) -> None:
        previous_timestamp = self.client.rows["TEST-001"]["updated_at"]
        updated = data_store.update_vehicle_mileage(
            "TEST-001", 24_000, "2026-11-05", "advisor_observed"
        )
        self.assertIsNotNone(updated)
        saved = self.client.rows["TEST-001"]["record"]
        self.assertEqual(saved["mileage"], 24_000)
        self.assertEqual(saved["mileageDate"], "2026-11-05")
        self.assertEqual(saved["mileageSource"], "advisor_observed")
        self.assertEqual(saved["history"], self.record["history"])
        self.assertEqual(saved["recs"], self.record["recs"])
        self.assertEqual(saved["obdTelemetry"], self.record["obdTelemetry"])
        self.assertNotEqual(self.client.rows["TEST-001"]["updated_at"], previous_timestamp)

    def test_mileage_below_history_is_marked_conflicting_without_replacing_evidence(self) -> None:
        updated = data_store.update_vehicle_mileage(
            "TEST-001", 19_500, "2026-11-05", "advisor_observed"
        )
        self.assertTrue(updated["conflicting"])
        self.assertEqual(updated["completeness"], "Conflicting mileage")
        self.assertEqual(updated["history"], self.record["history"])
        self.assertEqual(self.client.rows["TEST-001"]["record"]["recs"], self.record["recs"])

    def test_unknown_serial_is_not_inserted_by_mileage_update(self) -> None:
        before = copy.deepcopy(self.client.rows)
        self.assertIsNone(
            data_store.update_vehicle_mileage(
                "UNKNOWN", 24_000, "2026-11-05", "customer_reported"
            )
        )
        self.assertEqual(self.client.rows, before)

    def test_database_error_is_sanitized_and_never_falls_back_to_fixture(self) -> None:
        self.client.error = RuntimeError("secret key leaked by provider")
        with self.assertRaises(data_store.VehicleStoreUnavailableError) as raised:
            data_store.find_vehicle("TEST-001")
        self.assertNotIn("secret key", str(raised.exception))

    def test_database_row_contract_is_validated(self) -> None:
        self.client.rows["BROKEN"] = {"serial": "BROKEN", "record": {"serial": "OTHER"}}
        with self.assertRaises(data_store.VehicleStoreUnavailableError):
            data_store.load_vehicles()

    def test_seed_is_idempotent_and_imports_fixture_records(self) -> None:
        rows = [
            {"serial": "SEED-001", "record": {"serial": "SEED-001", "history": [], "recs": []}},
            {"serial": "SEED-002", "record": {"serial": "SEED-002", "history": [], "recs": []}},
        ]
        self.assertEqual(seed_vehicles(self.client, rows), 2)
        self.assertEqual(seed_vehicles(self.client, rows), 2)
        self.assertEqual(set(self.client.rows), {"TEST-001", "SEED-001", "SEED-002"})
        self.assertEqual(len(build_seed_rows()), 250)

    def test_seed_fixture_validation_rejects_bad_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vehicles.json"
            path.write_text(json.dumps({"BAD": {"serial": "OTHER", "history": [], "recs": []}}))
            with self.assertRaises(RuntimeError):
                build_seed_rows(path)

    def test_migration_enables_rls_and_denies_direct_client_access(self) -> None:
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase"
            / "migrations"
            / "20261105000100_create_vehicle_records.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("enable row level security", migration.lower())
        self.assertIn("revoke all on table public.vehicle_records from anon, authenticated", migration.lower())
        self.assertIn("grant all privileges on table public.vehicle_records to service_role", migration.lower())


if __name__ == "__main__":
    unittest.main()
