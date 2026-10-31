# FIT Analyzer

A dependency-free Python toolkit for parsing Garmin/Zwift FIT files and analyzing cycling and running activities.

**Version:** 1.0.0  
**Python:** 3.10+  
**Runtime dependencies:** none (Python standard library only)

## Features

- FIT binary decoder for standard FIT definition/data messages, including compressed timestamps.
- Record-level power, heart-rate, cadence, speed, distance, altitude and temperature extraction.
- Activity summaries: duration, distance, average/max power, HR and cadence.
- Cycling metrics: normalized power (30-second rolling average), intensity factor, TSS estimate, power-duration best efforts, and HR/power decoupling estimate.
- Basic interval detection from sustained power above a configurable FTP percentage.
- JSON and CSV exports.
- Intervals.icu personal API client and history downloader.
- Period comparison for 2025 rebuilding, 2026 AI-coaching and 2026 face-to-face-coaching periods.

## Quick start

### 1. Parse a FIT file

```bash
python -m fit_analyzer.cli analyze path/to/activity.fit --ftp 210 --weight 78
```

### 2. Export record streams

```bash
python -m fit_analyzer.cli analyze activity.fit --json-out activity_analysis.json --csv-out activity_records.csv
```

### 3. Run tests

```bash
python -m unittest discover -s tests -v
```

## Intervals.icu integration

Set your API key locally. Never commit it or paste it into chat.

macOS/Linux:
```bash
export INTERVALS_API_KEY="your_personal_api_key"
export INTERVALS_ATHLETE_ID="0"
```

Windows PowerShell:
```powershell
$env:INTERVALS_API_KEY="your_personal_api_key"
$env:INTERVALS_ATHLETE_ID="0"
```

Download your history:
```bash
python -m fit_analyzer.intervals_icu sync \
  --oldest 2025-01-01 --newest 2026-10-31 \
  --output data/intervals_icu
```

For best-effort power comparisons, request activity streams too:
```bash
python -m fit_analyzer.intervals_icu sync \
  --oldest 2025-01-01 --newest 2026-10-31 \
  --streams --output data/intervals_icu_streams
```

Compare periods:
```bash
python -m fit_analyzer.intervals_icu compare data/intervals_icu_streams/export.json --ftp 210 --weight 78
```

The API integration stores raw responses in local JSON. Those files can contain personal training and wellness information; keep them out of Git.

## FIT parser scope and limitations

This is a pure-Python FIT decoder for standard FIT files and common activity messages. It handles local message definitions, standard base types, developer-field payload skipping, and compressed timestamp headers. It currently focuses on common activity metrics; it is not intended to decode every manufacturer-specific FIT profile field. FIT CRC validation is available in strict mode.

Power-duration results depend on the sampling resolution in the FIT file. NP/TSS estimates use recorded power samples and should be compared only when recording conditions and FTP settings are consistent. HR drift is a screening metric, not a diagnosis or a standalone fitness verdict.

## Project layout

```text
fit-analyzer/
├── fit_analyzer/
│   ├── fit/
│   │   └── parser.py
│   ├── analytics/
│   │   └── cycling.py
│   ├── intervals_icu/
│   │   └── client.py
│   └── cli.py
├── tests/
├── data/                  # local exports; gitignored
├── .env.example
└── README.md
```

## Security

- API keys are read from environment variables.
- Never hard-code credentials.
- Local FIT files and Intervals.icu exports are ignored by Git.
- Revoke and replace an API key if it is accidentally exposed.

## Lap-aware interval analysis (v1.0.2)

The analyzer now reads FIT global-message 19 (lap) summaries and treats Garmin
lap markers as the primary interval boundaries. Every lap is retained in the
JSON report; sustained laps within 6–20 minutes and at or above 85% of the
provided FTP are flagged as `work_candidate`. If no such laps exist, the
analyzer falls back to automatic record-power detection.

Example:

```bash
fit-analyzer analyze sample_data/sample.fit --ftp 210 --weight 78 --json-out report.json
```

The report distinguishes `elapsed_duration_s` from `timer_duration_s` and
uses FIT session timer duration for the TSS estimate when available. Lap
classification is a heuristic; review the reported lap table before treating
it as a definitive workout prescription match.


### v1.0.2 timestamp correction

For Garmin lap messages, the analyzer derives the lap end timestamp from `start_time + total_elapsed_time` when both are available. This avoids non-monotonic lap timelines in FIT exports where the lap `timestamp` field repeats an earlier value. The original FIT timestamp remains the fallback when the derived value cannot be calculated.
