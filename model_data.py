#!/usr/bin/env python3
"""Download reproducible public FPL gameweek history outside source control."""

import argparse
import pathlib
import urllib.request

from fpl_api import UA

HISTORY_URL = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/"
    "master/data/{season}/gws/merged_gw.csv"
)


def history_path(directory, season):
    return pathlib.Path(directory) / f"{season}.csv"


def download_season(season, directory):
    """Fetch one immutable-season input, retaining it for repeatable backtests."""
    path = history_path(directory, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(HISTORY_URL.format(season=season),
                                     headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    if not payload.startswith(b"name,position,"):
        raise RuntimeError(f"unexpected history response for {season}")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", nargs="+", required=True)
    parser.add_argument("--history-dir", default="data/history")
    args = parser.parse_args()
    for season in args.season:
        print(download_season(season, args.history_dir))


if __name__ == "__main__":
    main()
