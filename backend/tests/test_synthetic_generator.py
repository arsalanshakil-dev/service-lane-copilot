"""Checks for the repeatable synthetic vehicle generator (issue #34)."""

from __future__ import annotations

import isolation  # noqa: F401  (must run before app imports)

import json
import random
import re
import unittest

import generate_synthetic_vehicles as gen
from seed_supabase import build_seed_rows


def miles(value: str) -> int | None:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


class SyntheticGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(gen.DATA_FILE.read_text(encoding="utf-8"))
        cls.generated = {k: v for k, v in cls.fixture.items() if k.startswith("DEMO-") and int(k[5:]) >= gen.FIRST_GENERATED}

    def test_fixture_has_1000_records_with_250_originals(self) -> None:
        self.assertEqual(len(self.fixture), 1000)
        self.assertEqual(len(self.generated), 750)
        self.assertEqual(min(self.generated), "DEMO-0251")
        self.assertEqual(max(self.generated), "DEMO-1000")
        for serial in ("NS-2048", "NS-5192", "DEMO-0011", "DEMO-0250"):
            self.assertIn(serial, self.fixture)

    def test_fixture_matches_the_generator_exactly(self) -> None:
        rng = random.Random(gen.SEED)
        template = self.fixture["DEMO-0011"]["obdTelemetry"]
        for index in range(gen.FIRST_GENERATED, 1001):
            record = gen.build_record(index, template, rng)
            self.assertEqual(record, self.fixture[record["serial"]], record["serial"])

    def test_generated_records_are_internally_consistent(self) -> None:
        for serial, record in self.generated.items():
            with self.subTest(serial=serial):
                readings = [m for m in (miles(h["mileage"]) for h in record["history"]) if m is not None]
                self.assertEqual(readings, sorted(readings, reverse=True), "history mileage must not increase going back in time")
                self.assertTrue(any(h["name"] == "Engine oil and filter" for h in record["history"]))
                self.assertIn(record["make"], {make for make, _ in gen.VEHICLE_LINES})
                for rec in record["recs"]:
                    since = int(re.search(r"([\d,]+) mi since service", rec["evidence"]).group(1).replace(",", ""))
                    if rec["status"] == "Due":
                        self.assertGreaterEqual(since, 5000)
                    else:
                        self.assertTrue(4000 <= since <= 5000)
                if record["conflicting"]:
                    self.assertLess(record["mileage"], readings[0])
                if record["completeness"] == "History incomplete":
                    self.assertIsNone(record["mileage"])
                    self.assertTrue(record["incomplete"])

    def test_scenarios_are_evenly_represented(self) -> None:
        counts: dict[str, int] = {}
        for record in self.generated.values():
            counts[record["completeness"]] = counts.get(record["completeness"], 0) + 1
        self.assertEqual(counts, {"Complete demo record": 375, "History incomplete": 125,
                                  "Mileage may be stale": 125, "Conflicting mileage": 125})

    def test_all_records_pass_seed_validation(self) -> None:
        rows = build_seed_rows()
        self.assertEqual(len(rows), 1000)


if __name__ == "__main__":
    unittest.main()
