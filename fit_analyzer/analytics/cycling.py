"""Cycling analytics with FIT lap-aware interval detection."""
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
    first_p, first_h = _mean([x[0] for x in paired[:mid]]), _mean([x[1] for x in paired[:mid]])
    second_p, second_h = _mean([x[0] for x in paired[mid:]]), _mean([x[1] for x in paired[mid:]])
    if not first_p or not second_p or not first_h or not second_h:
        return None
    first_eff, second_eff = first_p / first_h, second_p / second_h
    return (first_eff - second_eff) / first_eff * 100.0


def detect_power_intervals(
    records: List[Dict[str, Any]], ftp: float, threshold_fraction: float = 0.90,
    min_duration_s: int = 180,
) -> List[Dict[str, Any]]:
    """Fallback detector for sustained above-threshold record-power blocks."""
    threshold = ftp * threshold_fraction
    intervals: List[Dict[str, Any]] = []
    start = None
    samples: List[Dict[str, Any]] = []
    previous_time = None

    def close():
        nonlocal start, samples
        if start is not None and len(samples) >= min_duration_s:
            powers = _valid(r.get("power_w") for r in samples)
            hrs = _valid(r.get("heart_rate_bpm") for r in samples)
            cads = _valid(r.get("cadence_rpm") for r in samples)
            intervals.append({
                "source": "power_detection", "start_timestamp": start,
                "duration_s": len(samples), "avg_power_w": round(_mean(powers), 1) if powers else None,
                "avg_hr_bpm": round(_mean(hrs), 1) if hrs else None,
                "avg_cadence_rpm": round(_mean(cads), 1) if cads else None,
                "peak_power_w": max(powers) if powers else None,
            })
        start, samples = None, []

    for rec in records:
        power, ts = rec.get("power_w"), rec.get("timestamp")
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


def summarize_laps(messages: List[Dict[str, Any]], ftp: Optional[float] = None,
                   work_threshold_fraction: float = 0.85,
                   min_work_duration_s: int = 360,
                   max_work_duration_s: int = 1200) -> Dict[str, Any]:
    """Return every recorded lap and classify plausible sustained work laps.

    Lap markers are authoritative boundaries. A lap is a work candidate when
    its timer duration is in range and its average power meets the FTP fraction.
    This is a classification heuristic, not proof of the athlete's intent.
    """
    raw_laps = [m for m in messages if m.get("global_message") == 19]
    laps: List[Dict[str, Any]] = []
    work: List[Dict[str, Any]] = []
    for index, lap in enumerate(raw_laps, 1):
        duration = lap.get("total_timer_time_s") or lap.get("total_elapsed_time_s")
        avg_power = lap.get("avg_power_w")
        item = {
            "lap_number": index,
            "start_timestamp": lap.get("start_timestamp"),
            "end_timestamp": lap.get("end_timestamp"),
            "elapsed_duration_s": round(lap["total_elapsed_time_s"], 1) if lap.get("total_elapsed_time_s") is not None else None,
            "timer_duration_s": round(lap["total_timer_time_s"], 1) if lap.get("total_timer_time_s") is not None else None,
            "distance_km": round(lap["total_distance_m"] / 1000, 3) if lap.get("total_distance_m") is not None else None,
            "avg_power_w": avg_power, "max_power_w": lap.get("max_power_w"),
            "avg_hr_bpm": lap.get("avg_heart_rate_bpm"), "max_hr_bpm": lap.get("max_heart_rate_bpm"),
            "avg_cadence_rpm": lap.get("avg_cadence_rpm"),
        }
        is_work = bool(ftp and duration is not None and min_work_duration_s <= duration <= max_work_duration_s
                       and isinstance(avg_power, (int, float)) and avg_power >= ftp * work_threshold_fraction)
        item["classification"] = "work_candidate" if is_work else "other"
        laps.append(item)
        if is_work:
            work.append({**item, "source": "garmin_lap", "duration_s": item["timer_duration_s"] or item["elapsed_duration_s"]})
    return {"lap_count": len(laps), "laps": laps, "lap_work_intervals": work}


def analyze_records(records: List[Dict[str, Any]], ftp: Optional[float] = None,
                    weight_kg: Optional[float] = None) -> Dict[str, Any]:
    """Analyze decoded FIT messages; FIT session/lap summaries are retained."""
    all_messages = records
    record_messages = [r for r in all_messages if r.get("global_message") == 20]
    sessions = [m for m in all_messages if m.get("global_message") == 18]
    session = sessions[-1] if sessions else {}
    powers = _valid(r.get("power_w") for r in record_messages)
    hrs = _valid(r.get("heart_rate_bpm") for r in record_messages)
    cadences = _valid(r.get("cadence_rpm") for r in record_messages)
    distances = _valid(r.get("distance_m") for r in record_messages)
    timestamps = _valid(r.get("timestamp") for r in record_messages)
    elapsed_duration = session.get("total_elapsed_time_s")
    timer_duration = session.get("total_timer_time_s")
    duration = timer_duration or (max(timestamps) - min(timestamps) if len(timestamps) >= 2 else None)
    avg_power = session.get("avg_power_w") if session.get("avg_power_w") is not None else _mean(powers)
    np = _normalized_power(powers)
    intensity = np / ftp if np is not None and ftp else None
    tss = (duration * np * intensity / (ftp * 3600) * 100
           if duration and np is not None and intensity is not None and ftp else None)
    best = {label: rolling_best_power(powers, seconds) for label, seconds in
            (("5min", 300), ("12min", 720), ("20min", 1200), ("40min", 2400), ("60min", 3600))}
    lap_data = summarize_laps(all_messages, ftp=ftp)
    # Prefer explicit Garmin lap boundaries whenever any plausible work laps exist.
    detected = lap_data["lap_work_intervals"] or (detect_power_intervals(record_messages, ftp) if ftp else [])
    avg_hr = session.get("avg_heart_rate_bpm") if session.get("avg_heart_rate_bpm") is not None else _mean(hrs)
    max_hr = session.get("max_heart_rate_bpm") if session.get("max_heart_rate_bpm") is not None else (max(hrs) if hrs else None)
    avg_cadence = session.get("avg_cadence_rpm") if session.get("avg_cadence_rpm") is not None else _mean(cadences)
    return {
        "record_count": len(record_messages),
        "elapsed_duration_s": round(elapsed_duration, 1) if elapsed_duration is not None else None,
        "timer_duration_s": round(timer_duration, 1) if timer_duration is not None else None,
        "duration_s": round(duration, 1) if duration is not None else None,
        "distance_km": round((session.get("total_distance_m") or (max(distances) if distances else 0)) / 1000, 3) if (session.get("total_distance_m") is not None or distances) else None,
        "avg_power_w": round(avg_power, 1) if avg_power is not None else None,
        "max_power_w": session.get("max_power_w") if session.get("max_power_w") is not None else (max(powers) if powers else None),
        "normalized_power_w": round(np, 1) if np is not None else None,
        "avg_hr_bpm": round(avg_hr, 1) if avg_hr is not None else None,
        "max_hr_bpm": max_hr,
        "avg_cadence_rpm": round(avg_cadence, 1) if avg_cadence is not None else None,
        "ftp_w": ftp,
        "intensity_factor": round(intensity, 3) if intensity is not None else None,
        "tss_estimate": round(tss, 1) if tss is not None else None,
        "power_best_efforts_w": {k: round(v, 1) if v is not None else None for k, v in best.items()},
        "hr_power_decoupling_percent": round(_decoupling(record_messages), 2) if _decoupling(record_messages) is not None else None,
        "weight_kg": weight_kg,
        "best_efforts_w_per_kg": {k: round(v / weight_kg, 2) if v is not None and weight_kg else None for k, v in best.items()},
        "lap_count": lap_data["lap_count"],
        "laps": lap_data["laps"],
        "detected_intervals": detected,
        "interval_detection_method": "garmin_laps" if lap_data["lap_work_intervals"] else ("power_detection" if detected else "none"),
    }
