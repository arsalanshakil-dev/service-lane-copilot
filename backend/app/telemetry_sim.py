"""Deterministic simulated OBD-II telemetry recording (issue #52).

Builds a 5-minute, 1 Hz recording for the four demo streams, shaped like a short drive
(idle, pull away, cruise, slow down, stop, short drive) with small variation seeded from
the vehicle serial. Generated on request and never stored. It is POC data only: not
live OBD-II, not mileage, service history, diagnostic, or recommendation evidence.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

DURATION_SECONDS = 300
SAMPLE_RATE_HZ = 1
DEFAULT_CAPTURED_AT = "2026-11-05T09:30:00+05:00"
NOTICE = "Simulated 5-minute recording for the POC. No OBD-II adapter or physical vehicle is connected."

STREAMS = (
    ("engine_rpm", "Engine RPM", "rpm", 0, 3600),
    ("vehicle_speed", "Vehicle speed", "km/h", 0, 100),
    ("coolant_temperature", "Coolant temperature", "°C", 0, 120),
    ("calculated_engine_load", "Calculated engine load", "%", 0, 100),
)

# Drive profile: (end second, target speed km/h at that point). Speed is interpolated between points.
SPEED_PROFILE = ((0, 0), (25, 0), (55, 48), (80, 62), (150, 70), (175, 64), (205, 22), (225, 0),
                 (245, 0), (265, 35), (285, 42), (300, 30))


def _speed_at(second: float) -> float:
    for (t0, v0), (t1, v1) in zip(SPEED_PROFILE, SPEED_PROFILE[1:]):
        if t0 <= second <= t1:
            return v0 + (v1 - v0) * ((second - t0) / (t1 - t0) if t1 > t0 else 0)
    return float(SPEED_PROFILE[-1][1])


def _clamp(value: float, low: int, high: int) -> float:
    return max(low, min(high, value))


def _parse_captured_at(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromisoformat(DEFAULT_CAPTURED_AT)


def simulated_recording(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic simulated recording for a known vehicle record."""
    serial = str(vehicle.get("serial", ""))
    seed = int.from_bytes(hashlib.sha256(serial.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    stored = vehicle.get("obdTelemetry") if isinstance(vehicle.get("obdTelemetry"), dict) else {}
    end = _parse_captured_at(stored.get("capturedAt", DEFAULT_CAPTURED_AT))
    start = end - timedelta(seconds=DURATION_SECONDS - 1)

    speed_scale = rng.uniform(0.85, 1.25)           # this vehicle's typical pace
    idle_rpm = rng.uniform(720, 860)
    rpm_per_kmh = rng.uniform(26, 34)
    coolant_start, coolant_target = rng.uniform(70, 80), rng.uniform(88, 94)
    phase = rng.uniform(0, math.tau)

    series: dict[str, list[dict[str, Any]]] = {key: [] for key, *_ in STREAMS}
    previous_speed = 0.0
    for second in range(DURATION_SECONDS):
        timestamp = (start + timedelta(seconds=second)).isoformat(timespec="seconds")
        speed = _clamp(_speed_at(second) * speed_scale + math.sin(second / 9 + phase) * 1.8 + rng.uniform(-0.8, 0.8), 0, 100)
        if _speed_at(second) == 0:
            speed = 0.0
        accel = speed - previous_speed
        previous_speed = speed
        rpm = idle_rpm + speed * rpm_per_kmh + max(accel, 0) * 120 + rng.uniform(-25, 25)
        if speed > 55:
            rpm -= (speed - 55) * 9  # higher gear at cruise
        load = 14 + speed * 0.32 + max(accel, 0) * 9 + rng.uniform(-2, 2)
        if accel < -0.5:
            load = max(5, load - 12)  # coasting
        warm = 1 - math.exp(-second / 110)
        coolant = coolant_start + (coolant_target - coolant_start) * warm + math.sin(second / 23 + phase) * 0.6

        values = {
            "engine_rpm": round(_clamp(rpm, 0, 3600)),
            "vehicle_speed": round(speed, 1),
            "coolant_temperature": round(_clamp(coolant, 0, 120), 1),
            "calculated_engine_load": round(_clamp(load, 0, 100), 1),
        }
        for key, value in values.items():
            series[key].append({"timestamp": timestamp, "value": value})

    return {
        "serial": serial,
        "mode": "simulated",
        "status": "simulated",
        "source": "synthetic_recording_generator",
        "notice": NOTICE,
        "capturedAt": end.isoformat(timespec="seconds"),
        "durationSeconds": DURATION_SECONDS,
        "sampleRateHz": SAMPLE_RATE_HZ,
        "streams": [
            {"key": key, "label": label, "unit": unit, "samples": series[key]}
            for key, label, unit, _low, _high in STREAMS
        ],
    }
