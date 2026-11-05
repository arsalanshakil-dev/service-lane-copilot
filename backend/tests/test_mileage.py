from __future__ import annotations

import isolation  # noqa: F401  (must run before app imports)

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.main import ManualMileageUpdate, update_manual_mileage


class MileageApiTests(unittest.TestCase):
    def valid_payload(self, **overrides: object) -> ManualMileageUpdate:
        payload: dict[str, object] = {
            "mileage": 24_000,
            "mileageDate": date.today().isoformat(),
            "mileageSource": "advisor_observed",
        }
        payload.update(overrides)
        return ManualMileageUpdate(**payload)

    def test_route_replaces_current_reading_in_supabase_store(self) -> None:
        expected = {"serial": "TEST-001", "mileage": 24_000}
        with patch("app.main.update_vehicle_mileage", return_value=expected) as update:
            result = update_manual_mileage("TEST-001", self.valid_payload())

        self.assertEqual({k: v for k, v in result.items() if k != "rulesStatus"}, expected)
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
