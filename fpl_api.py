#!/usr/bin/env python3
"""Fantasy Premier League public API access.

Separate from the optimiser so the notifier does not drag in a MILP solver
just to read a fixture list.
"""

import json
import time
import urllib.error
import urllib.request

API = "https://fantasy.premierleague.com/api"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
UA = "cunha-matata-fpl/1.0 (+github.com/stevengonsalvez/fpl)"

RETRIES = 3
BACKOFF = 2  # seconds, doubled per attempt


def fetch(url, retries=RETRIES):
    """GET and decode JSON, retrying with backoff.

    With a two-hourly cron there is often exactly one run inside a deadline
    window, so a single blip must not cost the whole gameweek's alert.
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(BACKOFF * (2 ** attempt))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")


def get(path):
    return fetch(f"{API}/{path}")


def current_and_next_event(boot):
    """(current, next) gameweek. Either may be None between seasons."""
    cur = next((e for e in boot["events"] if e["is_current"]), None)
    nxt = next((e for e in boot["events"] if e["is_next"]), None)
    return cur, nxt
