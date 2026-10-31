from __future__ import annotations
from typing import Any, Dict, List
from fit_analyzer.analytics.cycling import rolling_best_power


PERIODS = {
    "2025_return_to_cycling": ("2025-01-01","2025-12-31"),
    "2026_AI_coaching": ("2026-01-01","2026-02-28"),
    "2026_face_to_face_coaching": ("2026-03-01","2026-10-31"),
}


def _date(summary):
    return str(summary.get("start_date_local") or summary.get("start_date") or "")[:10]


def _stream_data(streams):
    if isinstance(streams,dict):
        streams=streams.get("streams",streams)
        if isinstance(streams,dict):
            return {str(k).lower():v for k,v in streams.items() if isinstance(v,list)}
    if isinstance(streams,list):
        out={}
        for item in streams:
            if isinstance(item,dict):
                key=str(item.get("type") or item.get("name") or "").lower()
                data=item.get("data",item.get("values"))
                if key and isinstance(data,list): out[key]=data
        return out
    return {}


def compare_bundle(bundle: Dict[str,Any], ftp: float=210, weight: float=78):
    rows=[]
    for name,(start,end) in PERIODS.items():
        selected=[a for a in bundle.get("activities",[]) if start <= _date(a.get("summary",{})) <= end]
        power_by_duration={k:[] for k in ("5min","12min","20min","40min","60min")}
        total_hours=0.0
        for item in selected:
            summary=item.get("summary",{})
            kind=str(summary.get("type","")).lower()
            if kind and "ride" not in kind and "cycling" not in kind: continue
            seconds=summary.get("moving_time") or summary.get("elapsed_time") or 0
            if isinstance(seconds,(int,float)): total_hours += seconds/3600
            streams=_stream_data(item.get("streams"))
            watts=streams.get("watts") or streams.get("power") or []
            times=streams.get("time") or []
            sample=1.0
            if len(times)>1:
                diffs=[b-a for a,b in zip(times,times[1:]) if isinstance(a,(int,float)) and isinstance(b,(int,float)) and b>a]
                if diffs: sample=sorted(diffs)[len(diffs)//2]
            for label,duration in (("5min",300),("12min",720),("20min",1200),("40min",2400),("60min",3600)):
                value=rolling_best_power(watts,duration,sample)
                if value is not None: power_by_duration[label].append(value)
        best={k:(round(max(v),1) if v else None) for k,v in power_by_duration.items()}
        rows.append({"period":name,"start":start,"end":end,"activity_count":len(selected),
                     "training_hours":round(total_hours,1),"best_power_w":best,
                     "best_power_w_per_kg":{k:(round(v/weight,2) if v else None) for k,v in best.items()},
                     "ftp_reference_w":ftp})
    return {"periods":rows,"note":"Best efforts require downloaded activity streams. Activity counts include all activities returned in the date window; training hours and best power are filtered to ride/cycling activity types."}
