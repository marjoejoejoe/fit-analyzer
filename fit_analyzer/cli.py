from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from fit_analyzer.fit import FitParser
from fit_analyzer.analytics import analyze_records


def main():
    parser = argparse.ArgumentParser(prog="fit-analyzer", description="Analyze cycling FIT files.")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Parse and analyze a FIT activity.")
    analyze.add_argument("fit_file")
    analyze.add_argument("--ftp", type=float, default=None)
    analyze.add_argument("--weight", type=float, default=None)
    analyze.add_argument("--json-out", default=None)
    analyze.add_argument("--csv-out", default=None)
    analyze.add_argument("--strict-crc", action="store_true")
    args = parser.parse_args()

    if args.command == "analyze":
        decoded = FitParser(strict_crc=args.strict_crc).parse(args.fit_file)
        report = analyze_records(decoded, ftp=args.ftp, weight_kg=args.weight)
        print(json.dumps(report, indent=2))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps({"summary":report,"messages":decoded},indent=2),encoding="utf-8")
        if args.csv_out:
            records = [m for m in decoded if m.get("global_message") == 20]
            keys = sorted({k for row in records for k in row})
            with open(args.csv_out,"w",newline="",encoding="utf-8") as f:
                writer = csv.DictWriter(f,fieldnames=keys)
                writer.writeheader()
                writer.writerows(records)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
