from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path
from fit_analyzer.intervals_icu.client import IntervalsClient, IntervalsAPIError


def main():
    parser = argparse.ArgumentParser(prog="python -m fit_analyzer.intervals_icu")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--oldest", required=True)
    sync.add_argument("--newest", required=True)
    sync.add_argument("--output", default="data/intervals_icu")
    sync.add_argument("--streams", action="store_true")
    sync.add_argument("--pause", type=float, default=0.2)
    sync.add_argument("--limit", type=int, default=None)
    compare = sub.add_parser("compare")
    compare.add_argument("json_file")
    compare.add_argument("--ftp", type=float, default=210)
    compare.add_argument("--weight", type=float, default=78)
    args = parser.parse_args()

    if args.command == "sync":
        client = IntervalsClient()
        activities = client.activities(args.oldest,args.newest)
        if not isinstance(activities,list):
            raise IntervalsAPIError("Expected a list of activities from API.")
        if args.limit:
            activities = activities[:args.limit]
        bundle={"source":"Intervals.icu","exported_at_utc":datetime.now(timezone.utc).isoformat(),
                "date_range":{"oldest":args.oldest,"newest":args.newest},"activities":[],"wellness":[]}
        for i, summary in enumerate(activities,1):
            item={"summary":summary}
            aid=summary.get("id")
            if aid is not None:
                try:
                    item["detail"]=client.activity(aid)
                    if args.streams:
                        item["streams"]=client.streams(aid)
                except IntervalsAPIError as exc:
                    item["fetch_error"]=str(exc)
            bundle["activities"].append(item)
            if args.pause: time.sleep(args.pause)
            if i % 25 == 0: print(f"Fetched {i}/{len(activities)}")
        try:
            bundle["wellness"]=client.wellness(args.oldest,args.newest)
        except IntervalsAPIError as exc:
            bundle["wellness_error"]=str(exc)
        Path(args.output).mkdir(parents=True,exist_ok=True)
        out=Path(args.output)/f"intervals_{args.oldest}_{args.newest}.json"
        out.write_text(json.dumps(bundle,indent=2),encoding="utf-8")
        print(f"Saved {len(bundle['activities'])} activities: {out}")
    elif args.command == "compare":
        from fit_analyzer.analytics.periods import compare_bundle
        bundle=json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        print(json.dumps(compare_bundle(bundle,args.ftp,args.weight),indent=2))


if __name__ == "__main__":
    main()
