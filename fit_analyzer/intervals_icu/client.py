"""Dependency-free Intervals.icu API client."""
from __future__ import annotations

import base64
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class IntervalsAPIError(RuntimeError):
    pass


class IntervalsClient:
    def __init__(self, api_key=None, athlete_id=None, base_url="https://intervals.icu", timeout=30):
        self.api_key = (api_key or os.getenv("INTERVALS_API_KEY", "")).strip()
        self.athlete_id = str(athlete_id or os.getenv("INTERVALS_ATHLETE_ID", "0"))
        if not self.api_key:
            raise ValueError("Set INTERVALS_API_KEY in your environment; never hard-code it.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        token = base64.b64encode(("API_KEY:" + self.api_key).encode()).decode()
        self.auth = "Basic " + token

    def get(self, path, params=None, retries=2):
        url = self.base_url + "/api/v1/" + path.lstrip("/")
        if params:
            url += "?" + urlencode({k:v for k,v in params.items() if v is not None})
        req = Request(url, headers={"Authorization":self.auth,"Accept":"application/json","User-Agent":"FIT-Analyzer/1.0"})
        for attempt in range(retries + 1):
            try:
                with urlopen(req, timeout=self.timeout) as response:
                    raw = response.read()
                    return json.loads(raw.decode()) if raw else None
            except HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if (exc.code == 429 or 500 <= exc.code < 600) and attempt < retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise IntervalsAPIError(f"Intervals.icu HTTP {exc.code}: {body[:400]}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise IntervalsAPIError(f"Could not reach Intervals.icu: {exc}") from exc

    def activities(self, oldest, newest):
        return self.get(f"athlete/{self.athlete_id}/activities", {"oldest":oldest,"newest":newest})

    def activity(self, activity_id):
        return self.get(f"activity/{activity_id}", {"intervals":"true"})

    def streams(self, activity_id, types="watts,heartrate,cadence,time"):
        return self.get(f"activity/{activity_id}/streams.json", {"types":types})

    def wellness(self, oldest, newest):
        return self.get(f"athlete/{self.athlete_id}/wellness", {"oldest":oldest,"newest":newest})
