"""Checks for the paged vehicle records list (issue #36)."""

from __future__ import annotations

import unittest
from unittest.mock import patch


from app.main import search_vehicles
from seed_supabase import build_seed_rows
from test_obd_telemetry import FakeSupabase


class VehicleRecordsListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = build_seed_rows()
        cls.serials = sorted(row["serial"] for row in cls.rows)

    def setUp(self) -> None:
        self.client = FakeSupabase(self.rows)
        self.patcher = patch("app.data_store.get_supabase_client", return_value=self.client)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_first_page_has_total_and_is_ordered_by_serial(self) -> None:
        result = search_vehicles(q="", limit=25, offset=0)
        self.assertEqual(result["total"], len(self.rows))
        self.assertEqual(result["count"], 25)
        self.assertEqual([v["serial"] for v in result["vehicles"]], self.serials[:25])
        self.assertEqual((result["limit"], result["offset"]), (25, 0))

    def test_pages_do_not_overlap_and_cover_every_record(self) -> None:
        seen: list[str] = []
        offset = 0
        while True:
            page = search_vehicles(q="", limit=100, offset=offset)
            if not page["vehicles"]:
                break
            seen.extend(v["serial"] for v in page["vehicles"])
            offset += 100
        self.assertEqual(seen, self.serials)

    def test_summary_fields(self) -> None:
        vehicle = search_vehicles(q="NS-2048", limit=5, offset=0)["vehicles"][0]
        self.assertEqual(vehicle["serial"], "NS-2048")
        self.assertEqual((vehicle["make"], vehicle["model"], vehicle["year"]), ("Toyota", "Camry", 2021))
        self.assertEqual(vehicle["mileage"], 48120)
        self.assertEqual(vehicle["open_recommendations"], 3)
        self.assertEqual(vehicle["history_count"], 4)
        self.assertFalse(vehicle["incomplete"])
        incomplete = search_vehicles(q="NS-5192", limit=5, offset=0)["vehicles"][0]
        self.assertTrue(incomplete["incomplete"])

    def test_search_matches_make_model_year_case_insensitively(self) -> None:
        by_make = search_vehicles(q="northstar", limit=100, offset=0)
        self.assertGreater(by_make["total"], 0)
        self.assertTrue(all(v["make"] == "Northstar" for v in by_make["vehicles"]))
        self.assertEqual(search_vehicles(q="camry", limit=10, offset=0)["vehicles"][0]["model"], "Camry")

    def test_unknown_search_and_offset_past_end_return_empty_pages(self) -> None:
        none = search_vehicles(q="NO-SUCH-CAR", limit=25, offset=0)
        self.assertEqual((none["total"], none["count"], none["vehicles"]), (0, 0, []))
        past = search_vehicles(q="", limit=25, offset=len(self.rows) + 10)
        self.assertEqual((past["total"], past["vehicles"]), (len(self.rows), []))

    def test_listing_never_writes(self) -> None:
        before = {k: dict(v) for k, v in self.client.rows.items()}
        search_vehicles(q="", limit=100, offset=0)
        self.assertEqual(self.client.rows, before)


if __name__ == "__main__":
    unittest.main()
