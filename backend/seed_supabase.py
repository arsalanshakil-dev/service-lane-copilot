"""Idempotently seed synthetic vehicle fixtures into Supabase."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
DATA_FILE = PROJECT_ROOT / "data" / "vehicles.json"
BATCH_SIZE = 100


def build_seed_rows(data_file: Path = DATA_FILE) -> list[dict[str, Any]]:
    """Validate and convert the checked-in fixture to Supabase row payloads."""
    try:
        with data_file.open("r", encoding="utf-8") as source:
            vehicles = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not read the synthetic vehicle seed fixture.") from exc

    if not isinstance(vehicles, dict):
        raise RuntimeError("The synthetic vehicle seed fixture must be an object.")
    rows: list[dict[str, Any]] = []
    for serial, record in vehicles.items():
        normalized = str(serial).strip().upper()
        if (
            not normalized
            or not isinstance(record, dict)
            or record.get("serial") != normalized
            or not isinstance(record.get("history"), list)
            or not isinstance(record.get("recs"), list)
        ):
            raise RuntimeError(f"Invalid synthetic vehicle seed record for {serial!r}.")
        rows.append({"serial": normalized, "record": record})
    return rows


def supabase_client() -> Client:
    """Create a backend-only Supabase client from the ignored local env file."""
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env.")
    try:
        return create_client(url, key)
    except Exception as exc:
        raise RuntimeError("Could not initialize the Supabase client.") from exc


def seed_vehicles(client: Client, rows: list[dict[str, Any]], keep_existing: bool = False) -> int:
    """Upsert fixture rows by serial in bounded batches; safe to repeat.

    By default existing rows are refreshed from the fixture (advisor-saved changes are
    replaced). With keep_existing=True, only serials missing from the table are inserted
    (ON CONFLICT DO NOTHING), so mileage and services saved through the app are kept.
    """
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        client.table("vehicle_records").upsert(
            batch,
            on_conflict="serial",
            ignore_duplicates=keep_existing,
        ).execute()
    return len(rows)


def main() -> int:
    keep_existing = "--keep-existing" in sys.argv[1:]
    try:
        rows = build_seed_rows()
        seeded = seed_vehicles(supabase_client(), rows, keep_existing=keep_existing)
    except Exception:
        print(
            "Supabase seed failed. Check backend/.env, database availability, and that migrations are applied.",
            file=sys.stderr,
        )
        return 1
    mode = "inserted missing rows only; existing rows kept" if keep_existing else "existing rows refreshed from the fixture"
    print(f"Seeded {seeded} synthetic vehicle records into Supabase ({mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
