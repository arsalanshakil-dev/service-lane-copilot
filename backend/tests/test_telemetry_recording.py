"""Checks for the simulated OBD-II telemetry recording (issue #52)."""

from __future__ import annotations

import isolation  # noqa: F401  (must run before app imports)

import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException

from app.main import get_telemetry_recording
from app.telemetry_sim import DURATION_SECONDS, simulated_recording
from seed_supabase import build_seed_rows
from test_obd_telemetry import EXPECTED_STREAMS, FakeSupabase


class TelemetryRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = build_seed_rows()

    def setUp(self) -> None:
        self.client = FakeSupabase(self.rows)
        self.patcher = patch("app.data_store.get_supabase_client", return_value=self.client)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_recording_has_300_one_second_samples_per_stream_in_range(self) -> None:
        recording = get_telemetry_recording("NS-2048")
        self.assertEqual((recording["mode"], recording["status"]), ("simulated", "simulated"))
        self.assertIn("No OBD-II adapter", recording["notice"])
        self.assertEqual((recording["durationSeconds"], recording["sampleRateHz"]), (300, 1))
        self.assertEqual({s["key"] for s in recording["streams"]}, set(EXPECTED_STREAMS))
        for stream in recording["streams"]:
            label, unit, low, high = EXPECTED_STREAMS[stream["key"]]
            with self.subTest(stream=stream["key"]):
                self.assertEqual((stream["label"], stream["unit"]), (label, unit))
                self.assertEqual(len(stream["samples"]), DURATION_SECONDS)
                times = [datetime.fromisoformat(s["timestamp"]) for s in stream["samples"]]
                self.assertTrue(all((b - a).total_seconds() == 1 for a, b in zip(times, times[1:])))
                self.assertEqual(times[-1], datetime.fromisoformat(recording["capturedAt"]))
                self.assertTrue(all(low <= s["value"] <= high for s in stream["samples"]))

    def test_recording_is_deterministic_and_differs_between_vehicles(self) -> None:
        self.assertEqual(get_telemetry_recording("NS-2048"), get_telemetry_recording("NS-2048"))
        a = get_telemetry_recording("NS-2048")["streams"][0]["samples"]
        b = get_telemetry_recording("DEMO-0011")["streams"][0]["samples"]
        self.assertNotEqual([s["value"] for s in a], [s["value"] for s in b])

    def test_drive_profile_starts_and_stops(self) -> None:
        speed = next(s for s in get_telemetry_recording("NS-2048")["streams"] if s["key"] == "vehicle_speed")["samples"]
        self.assertEqual(speed[0]["value"], 0)       # idle at the start
        self.assertGreater(max(s["value"] for s in speed[60:180]), 40)  # cruising
        self.assertEqual(speed[235]["value"], 0)     # stopped

    def test_unknown_serial_is_404_and_nothing_is_written(self) -> None:
        before = copy.deepcopy(self.client.rows)
        with self.assertRaises(HTTPException) as caught:
            get_telemetry_recording("NOPE-1")
        self.assertEqual(caught.exception.status_code, 404)
        get_telemetry_recording("NS-2048")
        self.assertEqual(self.client.rows, before)

    def test_vehicle_without_stored_telemetry_still_gets_a_recording(self) -> None:
        recording = simulated_recording({"serial": "NEW-1"})
        self.assertEqual(len(recording["streams"][0]["samples"]), DURATION_SECONDS)


if __name__ == "__main__":
    unittest.main()
