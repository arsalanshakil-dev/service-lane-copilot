"""Append repeatable fictional vehicle records to the synthetic seed fixture (issue #34).

The original 250 records (NS-*, DEMO-0011..DEMO-0250) are never modified. New records
DEMO-0251..DEMO-<count> are generated from a fixed seed, so running this again produces
identical output. Every make, model, date, and reading is fictional demo content.

Usage (from backend/):
    python generate_synthetic_vehicles.py            # build up to 1,000 records
    python generate_synthetic_vehicles.py --count 1500
Then load them with: python seed_supabase.py
"""

from __future__ import annotations

import argparse
import copy
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "vehicles.json"
SEED = 20261105
FIRST_GENERATED = 251

# Fictional makes/models only (no real manufacturers).
VEHICLE_LINES = [
    ("Northstar", "Alder"), ("Northstar", "Ridge"),
    ("Pinecrest", "Trail"), ("Pinecrest", "Canyon"),
    ("Westfield", "Cedar"), ("Westfield", "Prairie"),
    ("Clearwater", "Summit"), ("Clearwater", "Delta"),
    ("Redwood", "Harbor"), ("Redwood", "Grove"),
    ("Silverline", "Meadow"), ("Silverline", "Orbit"),
    ("Brookhaven", "Vista"), ("Brookhaven", "Pioneer"),
    ("Ironvale", "Forge"), ("Ironvale", "Sierra"),
]

# Fictional history entries: (name, detail). Oil, rotation, and inspection always appear.
CORE_SERVICES = [
    ("Engine oil and filter", "Synthetic routine service entry"),
    ("Tire rotation", "Synthetic service history entry"),
    ("Vehicle inspection", "Synthetic inspection entry"),
]
EXTRA_SERVICES = [
    ("Cabin air filter", "Synthetic filter replacement entry"),
    ("Wiper blades", "Synthetic wiper replacement entry"),
    ("Battery test", "Synthetic battery check entry"),
    ("Brake inspection", "Synthetic brake inspection entry"),
    ("Engine air filter", "Synthetic filter replacement entry"),
]

SCENARIOS = ["due", "soon", "none", "history_incomplete", "stale", "conflicting"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _miles(value: int) -> str:
    return f"{value:,} mi"


def _history_date(months_ago: int) -> str:
    """Fixed reference month (Oct 2026) so output never depends on the run date."""
    total = 2026 * 12 + 9 - months_ago
    return f"{MONTHS[total % 12]} 15, {total // 12}"


def _telemetry(template: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Reuse the existing simulated-telemetry structure with new in-range values."""
    telemetry = copy.deepcopy(template)
    base = {
        "engine_rpm": [rng.randint(760, 860) + step for step in (0, 400, 960, 1380)],
        "vehicle_speed": [s + rng.randint(0, 4) for s in (0, 14, 32, 46)],
        "coolant_temperature": [rng.randint(84, 92) + step for step in (0, 1, 2, 3)],
        "calculated_engine_load": [rng.randint(12, 22) + step for step in (0, 13, 28, 42)],
    }
    for stream in telemetry["streams"]:
        for sample, value in zip(stream["samples"], base[stream["key"]]):
            sample["value"] = value
    return telemetry


def build_record(index: int, template_telemetry: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    serial = f"DEMO-{index:04d}"
    make, model = VEHICLE_LINES[(index * 7) % len(VEHICLE_LINES)]
    year = 2018 + index % 8
    scenario = SCENARIOS[index % len(SCENARIOS)]

    # Odometer readings follow the vehicle's age and its own monthly driving rate, so an
    # older history entry always has proportionally lower mileage than a newer one.
    age_months = (2026 - year) * 12 + 10
    rate = rng.randint(700, 1_300)  # fictional miles per month
    current = max(3_000, age_months * rate + rng.randint(-1_500, 1_500))
    oil_since = {"due": rng.randint(5_050, 6_400), "soon": rng.randint(4_000, 4_950)}.get(scenario, rng.randint(600, 3_800))
    oil_months = max(1, round(oil_since / rate))

    def reading(months_ago: int) -> int:
        return current - months_ago * rate + rng.randint(-150, 150)

    events = [(oil_months, *CORE_SERVICES[0], current - oil_since)]
    for (name, detail), months_ago in ((CORE_SERVICES[1], oil_months + rng.randint(2, 5)),
                                      (CORE_SERVICES[2], oil_months + rng.randint(8, 14))):
        events.append((months_ago, name, detail, reading(months_ago)))
    for name, detail in rng.sample(EXTRA_SERVICES, rng.randint(0, 3)):
        months_ago = rng.randint(1, 30)
        events.append((months_ago, name, detail, reading(months_ago)))
    # Newest first; drop entries that would predate the vehicle, and keep readings monotonic.
    events = [event for event in events if event[0] < age_months and event[3] > 0]
    events.sort(key=lambda event: (event[0], -event[3]))
    history, previous = [], current
    for months_ago, name, detail, miles in events:
        miles = min(miles, previous)
        previous = miles
        history.append({"date": _history_date(months_ago), "name": name, "detail": detail, "mileage": _miles(miles)})

    record: dict[str, Any] = {
        "serial": serial, "make": make, "model": model, "year": year,
        "mileage": current, "mileageDate": "Recorded in demo", "completeness": "Complete demo record",
        "history": history, "recs": [], "incomplete": False, "conflicting": False,
    }
    oil_event = next(event for event in history if event["name"] == CORE_SERVICES[0][0])
    last_oil = int(oil_event["mileage"].replace(",", "").split()[0])
    evidence = f"Last recorded at {_miles(last_oil)} · Current recorded mileage {_miles(current)} · {current - last_oil:,} mi since service"
    if scenario == "due":
        record["recs"] = [{
            "name": "Engine oil and filter", "status": "Due", "kind": "due",
            "text": "The fictional demo interval has been reached since the last recorded oil service.",
            "evidence": evidence, "rule": "Synthetic demo rule: due at 5,000 mi since last service.", "safety": False,
        }]
    elif scenario == "soon":
        record["recs"] = [{
            "name": "Engine oil and filter", "status": "Coming up", "kind": "soon",
            "text": "The fictional demo interval places an oil service in the coming-up range.",
            "evidence": evidence, "rule": "Synthetic demo rule: coming up between 4,000 and 5,000 mi since last service.",
            "safety": False,
        }]
    elif scenario == "history_incomplete":
        record.update(mileage=None, mileageDate="Mileage not recorded", completeness="History incomplete", incomplete=True)
        for event in history[:2]:
            event["detail"] = "Synthetic service entry · mileage not recorded"
            event["mileage"] = "—"
    elif scenario == "stale":
        record.update(mileageDate=f"Recorded {rng.randint(9, 14)} months ago", completeness="Mileage may be stale", incomplete=True)
    elif scenario == "conflicting":
        newest = int(history[0]["mileage"].replace(",", "").split()[0])
        record.update(mileage=max(0, newest - rng.randint(80, 400)), completeness="Conflicting mileage",
                      incomplete=True, conflicting=True)

    record["obdTelemetry"] = _telemetry(template_telemetry, rng)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1000, help="total records after generation (default 1000)")
    args = parser.parse_args()

    data: dict[str, Any] = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    original = {key: value for key, value in data.items()
                if not (key.startswith("DEMO-") and int(key[5:]) >= FIRST_GENERATED)}
    if len(original) != 250:
        raise SystemExit(f"Expected the 250 original records, found {len(original)}.")
    if args.count < len(original):
        raise SystemExit("--count cannot be lower than the 250 original records.")

    template = original["DEMO-0011"]["obdTelemetry"]
    rng = random.Random(SEED)
    generated = {}
    for index in range(FIRST_GENERATED, FIRST_GENERATED + args.count - len(original)):
        record = build_record(index, template, rng)
        generated[record["serial"]] = record

    output = {**original, **generated}
    DATA_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(output)} records ({len(generated)} generated) to {DATA_FILE} on {date.today().isoformat()}.")


if __name__ == "__main__":
    main()
