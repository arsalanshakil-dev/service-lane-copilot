from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app import data_store
from app.main import capabilities, get_vehicle
from fastapi import HTTPException

EXPECTED_STREAMS = {
    "engine_rpm": ("Engine RPM", "rpm", 0, 3600),
    "vehicle_speed": ("Vehicle speed", "km/h", 0, 100),
    "coolant_temperature": ("Coolant temperature", "°C", 0, 120),
    "calculated_engine_load": ("Calculated engine load", "%", 0, 100),
}


class SimulatedObdTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        data_store.load_vehicles.cache_clear()
        cls.vehicles = data_store.load_vehicles()

    def test_all_synthetic_records_have_valid_simulated_streams(self) -> None:
        self.assertEqual(len(self.vehicles), 250)
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
        expected_telemetry = copy.deepcopy(original["obdTelemetry"])
        expected_history = copy.deepcopy(original["history"])
        expected_recs = copy.deepcopy(original["recs"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_path = Path(temporary_directory) / "vehicles.json"
            data_path.write_text(json.dumps({"TEST-OBD": original}), encoding="utf-8")
            with patch.object(data_store, "DATA_FILE", data_path):
                data_store.load_vehicles.cache_clear()
                updated = data_store.update_vehicle_mileage(
                    "TEST-OBD", 50_000, "2026-11-05", "advisor_observed"
                )
                self.assertIsNotNone(updated)
                self.assertEqual(updated["obdTelemetry"], expected_telemetry)
                self.assertEqual(updated["history"], expected_history)
                self.assertEqual(updated["recs"], expected_recs)
                self.assertEqual(updated["mileage"], 50_000)
        data_store.load_vehicles.cache_clear()


if __name__ == "__main__":
    unittest.main()
