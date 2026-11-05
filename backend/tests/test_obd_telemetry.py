from __future__ import annotations

import copy
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app import data_store
from app.main import capabilities, get_vehicle
from fastapi import HTTPException
from seed_supabase import build_seed_rows

EXPECTED_STREAMS = {
    "engine_rpm": ("Engine RPM", "rpm", 0, 3600),
    "vehicle_speed": ("Vehicle speed", "km/h", 0, 100),
    "coolant_temperature": ("Coolant temperature", "°C", 0, 120),
    "calculated_engine_load": ("Calculated engine load", "%", 0, 100),
}


class FakeSupabase:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = {row["serial"]: copy.deepcopy(row) for row in rows}

    def table(self, name: str) -> "FakeQuery":
        if name != data_store.VEHICLE_TABLE:
            raise AssertionError(f"Unexpected table: {name}")
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, client: FakeSupabase) -> None:
        self.client = client
        self.operation = "select"
        self.filters: dict[str, object] = {}
        self.payload: dict | None = None
        self.row_limit: int | None = None
        self.order_by: str | None = None

    def select(self, _columns: str) -> "FakeQuery":
        return self

    def eq(self, column: str, value: object) -> "FakeQuery":
        self.filters[column] = value
        return self

    def order(self, column: str) -> "FakeQuery":
        self.order_by = column
        return self

    def limit(self, count: int) -> "FakeQuery":
        self.row_limit = count
        return self

    def update(self, payload: dict) -> "FakeQuery":
        self.operation = "update"
        self.payload = copy.deepcopy(payload)
        return self

    def insert(self, payload: dict) -> "FakeQuery":
        self.operation = "insert"
        self.payload = copy.deepcopy(payload)
        return self

    def delete(self) -> "FakeQuery":
        self.operation = "delete"
        return self

    def execute(self) -> SimpleNamespace:
        if self.operation == "insert":
            assert self.payload is not None
            if self.payload["serial"] in self.client.rows:
                raise RuntimeError("duplicate key value violates unique constraint")
            self.client.rows[self.payload["serial"]] = copy.deepcopy(self.payload)
            return SimpleNamespace(data=[copy.deepcopy(self.payload)])
        if self.operation == "delete":
            serial = self.filters.get("serial")
            removed = self.client.rows.pop(serial, None) if isinstance(serial, str) else None
            return SimpleNamespace(data=[removed] if removed else [])
        if self.operation == "update":
            serial = self.filters.get("serial")
            if not isinstance(serial, str) or serial not in self.client.rows:
                return SimpleNamespace(data=[])
            assert self.payload is not None
            self.client.rows[serial].update(copy.deepcopy(self.payload))
            return SimpleNamespace(data=[{"serial": serial}])

        rows = [
            copy.deepcopy(row)
            for row in self.client.rows.values()
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.order_by is not None:
            rows.sort(key=lambda row: row[self.order_by])
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return SimpleNamespace(data=rows)


class SimulatedObdTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seed_rows = build_seed_rows()
        cls.vehicles = {row["serial"]: row["record"] for row in cls.seed_rows}

    def setUp(self) -> None:
        self.client = FakeSupabase(self.seed_rows)
        self.client_patch = patch(
            "app.data_store.get_supabase_client", return_value=self.client
        )
        self.client_patch.start()

    def tearDown(self) -> None:
        self.client_patch.stop()

    def test_all_synthetic_records_have_valid_simulated_streams(self) -> None:
        self.assertEqual(len(self.vehicles), 1000)
        for serial, vehicle in self.vehicles.items():
            with self.subTest(serial=serial):
                telemetry = vehicle["obdTelemetry"]
                self.assertEqual(telemetry["mode"], "simulated")
                self.assertEqual(telemetry["status"], "simulated")
                self.assertEqual(telemetry["source"], "synthetic_demo_generator")
                self.assertIn("No OBD-II adapter", telemetry["notice"])
                streams = telemetry["streams"]
                self.assertEqual({stream["key"] for stream in streams}, set(EXPECTED_STREAMS))
                for stream in streams:
                    label, unit, minimum, maximum = EXPECTED_STREAMS[stream["key"]]
                    self.assertEqual(stream["label"], label)
                    self.assertEqual(stream["unit"], unit)
                    self.assertEqual(len(stream["samples"]), 4)
                    times = []
                    for sample in stream["samples"]:
                        parsed = datetime.fromisoformat(sample["timestamp"])
                        self.assertIsNotNone(parsed.tzinfo)
                        times.append(parsed)
                        self.assertIsInstance(sample["value"], (int, float))
                        self.assertGreaterEqual(sample["value"], minimum)
                        self.assertLessEqual(sample["value"], maximum)
                    self.assertEqual(times, sorted(times))
                    self.assertEqual(times[-1].isoformat(), telemetry["capturedAt"])

    def test_known_vehicle_exposes_repeatable_telemetry_without_changing_evidence(self) -> None:
        first = data_store.find_vehicle("NS-2048")
        second = data_store.find_vehicle("NS-2048")
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first["obdTelemetry"]["mode"], "simulated")
        self.assertEqual(first["recs"], self.vehicles["NS-2048"]["recs"])
        self.assertEqual(first["history"], self.vehicles["NS-2048"]["history"])
        self.assertEqual(first["mileage"], self.vehicles["NS-2048"]["mileage"])

    def test_unknown_serial_has_no_telemetry(self) -> None:
        self.assertIsNone(data_store.find_vehicle("UNKNOWN-OBD"))

    def test_vehicle_api_returns_telemetry_and_unknown_serial_is_404(self) -> None:
        known = get_vehicle("NS-2048")
        self.assertEqual(known["obdTelemetry"]["status"], "simulated")
        self.assertEqual(len(known["obdTelemetry"]["streams"]), 4)
        with self.assertRaises(HTTPException) as raised:
            get_vehicle("UNKNOWN-OBD")
        self.assertEqual(raised.exception.status_code, 404)

    def test_backend_capabilities_document_simulated_record_data(self) -> None:
        data_fields = capabilities()["rest"]["vehicle_record_data"]
        self.assertIn("simulated OBD telemetry", data_fields)

    def test_manual_mileage_replacement_preserves_telemetry_and_service_evidence(self) -> None:
        original = copy.deepcopy(self.vehicles["NS-2048"])
        original["serial"] = "TEST-OBD"
        self.client.rows["TEST-OBD"] = {
            "serial": "TEST-OBD",
            "record": copy.deepcopy(original),
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        expected_telemetry = copy.deepcopy(original["obdTelemetry"])
        expected_history = copy.deepcopy(original["history"])
        expected_recs = copy.deepcopy(original["recs"])

        updated = data_store.update_vehicle_mileage(
            "TEST-OBD", 50_000, "2026-11-05", "advisor_observed"
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated["obdTelemetry"], expected_telemetry)
        self.assertEqual(updated["history"], expected_history)
        self.assertEqual(updated["recs"], expected_recs)
        self.assertEqual(updated["mileage"], 50_000)
        self.assertEqual(self.client.rows["TEST-OBD"]["record"]["mileageDate"], "2026-11-05")
        self.assertEqual(
            self.client.rows["TEST-OBD"]["record"]["mileageSource"], "advisor_observed"
        )


if __name__ == "__main__":
    unittest.main()
