from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import data_store
from app.main import ManualMileageUpdate, update_manual_mileage


class MileageStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temporary_directory.name) / "vehicles.json"
        self.original_record = {
            "serial": "TEST-001",
            "mileage": 22_500,
            "mileageDate": "2026-01-01",
            "mileageSource": "customer_reported",
            "completeness": "Complete demo record",
            "incomplete": False,
            "conflicting": False,
            "history": [{"mileage": "20,000 mi"}],
            "recs": [],
        }
        self.data_path.write_text(
            json.dumps({"TEST-001": self.original_record}),
            encoding="utf-8",
        )
        self.data_file_patch = patch.object(data_store, "DATA_FILE", self.data_path)
        self.data_file_patch.start()
        data_store.load_vehicles.cache_clear()

    def tearDown(self) -> None:
        data_store.load_vehicles.cache_clear()
        self.data_file_patch.stop()
        self.temporary_directory.cleanup()

    def test_replaces_existing_mileage_and_provenance(self) -> None:
        updated = data_store.update_vehicle_mileage(
            "test-001",
            24_000,
            "2026-11-05",
            "advisor_observed",
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated["mileage"], 24_000)
        self.assertEqual(updated["mileageDate"], "2026-11-05")
        self.assertEqual(updated["mileageSource"], "advisor_observed")
        saved = json.loads(self.data_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["TEST-001"]["mileage"], 24_000)
        self.assertEqual(saved["TEST-001"]["mileageSource"], "advisor_observed")

    def test_unknown_serial_does_not_change_dataset(self) -> None:
        before = self.data_path.read_text(encoding="utf-8")

        updated = data_store.update_vehicle_mileage(
            "UNKNOWN",
            24_000,
            "2026-11-05",
            "customer_reported",
        )

        self.assertIsNone(updated)
        self.assertEqual(self.data_path.read_text(encoding="utf-8"), before)

    def test_reading_below_service_history_is_marked_conflicting(self) -> None:
        updated = data_store.update_vehicle_mileage(
            "TEST-001",
            19_500,
            "2026-11-05",
            "advisor_observed",
        )

        self.assertIsNotNone(updated)
        self.assertTrue(updated["conflicting"])
        self.assertEqual(updated["completeness"], "Conflicting mileage")


class MileageApiTests(unittest.TestCase):
    def valid_payload(self, **overrides: object) -> ManualMileageUpdate:
        payload: dict[str, object] = {
            "mileage": 24_000,
            "mileageDate": date.today().isoformat(),
            "mileageSource": "advisor_observed",
        }
        payload.update(overrides)
        return ManualMileageUpdate(**payload)

    def test_route_replaces_current_reading(self) -> None:
        expected = {"serial": "TEST-001", "mileage": 24_000}
        with patch("app.main.update_vehicle_mileage", return_value=expected) as update:
            result = update_manual_mileage("TEST-001", self.valid_payload())

        self.assertEqual(result, expected)
        update.assert_called_once_with(
            "TEST-001",
            24_000,
            date.today().isoformat(),
            "advisor_observed",
        )

    def test_unknown_serial_returns_404(self) -> None:
        with patch("app.main.update_vehicle_mileage", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                update_manual_mileage("UNKNOWN", self.valid_payload())

        self.assertEqual(raised.exception.status_code, 404)

    def test_future_date_returns_422_without_writing(self) -> None:
        future_date = (date.today() + timedelta(days=1)).isoformat()
        with patch("app.main.update_vehicle_mileage") as update:
            with self.assertRaises(HTTPException) as raised:
                update_manual_mileage(
                    "TEST-001",
                    self.valid_payload(mileageDate=future_date),
                )

        self.assertEqual(raised.exception.status_code, 422)
        update.assert_not_called()

    def test_negative_fractional_and_invalid_source_are_rejected(self) -> None:
        for value in (-1, 19_500.5):
            with self.subTest(mileage=value):
                with self.assertRaises(ValidationError):
                    self.valid_payload(mileage=value)

        with self.assertRaises(ValidationError):
            self.valid_payload(mileageSource="obd_guess")


if __name__ == "__main__":
    unittest.main()
