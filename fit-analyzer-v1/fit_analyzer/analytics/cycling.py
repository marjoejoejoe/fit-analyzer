"""Cycling analytics calculated from decoded FIT record messages."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence


def _valid(values: Iterable[Any]) -> List[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def rolling_best_power(power: Sequence[Any], seconds: int, sample_seconds: float = 1.0) -> Optional[float]:
    values = _valid(power)
    window = max(1, int(round(seconds / sample_seconds)))
    if len(values) < window:
        return None
    current = sum(values[:window])
    best = current
    for i in range(window, len(values)):
        current += values[i] - values[i-window]
        best = max(best, current)
    return best / window


def _normalized_power(power: Sequence[Any], sample_seconds: float = 1.0) -> Optional[float]:
    values = _valid(power)
    window = max(1, int(round(30 / sample_seconds)))
    if len(values) < window:
        return None
    rolling = []
    total = sum(values[:window])
    rolling.append(total / window)
    for i in range(window, len(values)):
        total += values[i] - values[i-window]
        rolling.append(total / window)
    return (sum(x ** 4 for x in rolling) / len(rolling)) ** 0.25


def _decoupling(records: List[Dict[str, Any]]) -> Optional[float]:
    # Compare HR/power ratio in first and second halves; only use paired samples.
    paired = [
        (float(r["power_w"]), float(r["heart_rate_bpm"]))
        for r in records
        if isinstance(r.get("power_w"), (int, float))
        and isinstance(r.get("heart_rate_bpm"), (int, float))
        and r["power_w"] >= 50 and r["heart_rate_bpm"] >= 60
    ]
    if len(paired) < 60:
        return None
    mid = len(paired) // 2
    first_p = _mean([x[0] for x in paired[:mid]])
    first_h = _mean([x[1] for x in paired[:mid]])
    second_p = _mean([x[0] for x in paired[mid:]])
    second_h = _mean([x[1] for x in paired[mid:]])
    if not first_p or not second_p or not first_h or not second_h:
        return None
    first_eff = first_p / first_h
    second_eff = second_p / second_h
    return (first_eff - second_eff) / first_eff * 100.0


def detect_power_intervals(
    records: List[Dict[str, Any]],
    ftp: float,
    threshold_fraction: float = 0.90,
    min_duration_s: int = 180,
) -> List[Dict[str, Any]]:
    """Find contiguous above-threshold blocks, assuming approximately 1 Hz records."""
    threshold = ftp * threshold_fraction
    intervals = []
    start = None
    samples = []
    previous_time = None

    def close():
        nonlocal start, samples
        if start is not None and len(samples) >= min_duration_s:
            powers = _valid([r.get("power_w") for r in samples])
            hrs = _valid([r.get("heart_rate_bpm") for r in samples])
            intervals.append({
                "start_timestamp": start,
                "duration_s": len(samples),
                "avg_power_w": round(_mean(powers), 1) if powers else None,
                "avg_hr_bpm": round(_mean(hrs), 1) if hrs else None,
                "peak_power_w": max(powers) if powers else None,
            })
        start, samples = None, []

    for rec in records:
        power = rec.get("power_w")
        ts = rec.get("timestamp")
        valid = isinstance(power, (int, float)) and power >= threshold
        if samples and ts is not None and previous_time is not None and ts - previous_time > 2:
            close()
        if valid:
            if start is None:
                start = ts
            samples.append(rec)
        else:
            close()
        previous_time = ts if ts is not None else previous_time
    close()
    return intervals


def analyze_records(
    records: List[Dict[str, Any]],
    ftp: Optional[float] = None,
    weight_kg: Optional[float] = None,
) -> Dict[str, Any]:
    records = [r for r in records if r.get("global_message") == 20]
    powers = _valid(r.get("power_w") for r in records)
    hrs = _valid(r.get("heart_rate_bpm") for r in records)
    cadences = _valid(r.get("cadence_rpm") for r in records)
    distances = _valid(r.get("distance_m") for r in records)
    timestamps = _valid(r.get("timestamp") for r in records)
    duration = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else None
    avg_power = _mean(powers)
    np = _normalized_power(powers)
    intensity = np / ftp if np is not None and ftp else None
    tss = (duration * np * intensity / (ftp * 3600) * 100 if duration and np and intensity and ftp else None)

    best = {}
    for label, seconds in (("5min",300),("12min",720),("20min",1200),("40min",2400),("60min",3600)):
        best[label] = rolling_best_power(powers, seconds)

    result = {
        "record_count": len(records),
        "duration_s": duration,
        "distance_km": round(max(distances) / 1000, 3) if distances else None,
        "avg_power_w": round(avg_power, 1) if avg_power is not None else None,
        "max_power_w": max(powers) if powers else None,
        "normalized_power_w": round(np, 1) if np is not None else None,
        "avg_hr_bpm": round(_mean(hrs), 1) if hrs else None,
        "max_hr_bpm": max(hrs) if hrs else None,
        "avg_cadence_rpm": round(_mean(cadences), 1) if cadences else None,
        "ftp_w": ftp,
        "intensity_factor": round(intensity, 3) if intensity is not None else None,
        "tss_estimate": round(tss, 1) if tss is not None else None,
        "power_best_efforts_w": {k: round(v, 1) if v is not None else None for k,v in best.items()},
        "hr_power_decoupling_percent": round(_decoupling(records), 2) if _decoupling(records) is not None else None,
        "weight_kg": weight_kg,
        "best_efforts_w_per_kg": {
            k: round(v / weight_kg, 2) if v is not None and weight_kg else None
            for k,v in best.items()
        },
        "detected_intervals": detect_power_intervals(records, ftp) if ftp else [],
    }
    return result
