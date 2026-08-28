#!/usr/bin/env python3
"""Download public FPL history and run the pre-use model gate."""

import argparse
import pathlib

from model_data import download_season, history_path
from points_model import load_samples, walk_forward


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--history-dir", default="data/history")
    parser.add_argument("--holdout", type=int, default=4)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    paths = [download_season(season, args.history_dir) for season in args.season]
    result = walk_forward(load_samples(paths), args.season[-1], args.holdout)
    print(f"walk-forward {result['season']} GW{result['gameweeks'][0]}-{result['gameweeks'][-1]} "
          f"({result['rows']} fixtures)")
    print(f"points MAE: model {result['model_mae']:.3f}, naive {result['naive_mae']:.3f}")
    print(f"minutes MAE: model {result['minutes_model_mae']:.3f}, naive {result['minutes_naive_mae']:.3f}")
    print("PASS: validation gate met, recommendation-only" if result["passed"] else "FAIL: recommendation-only")
    if args.require_pass and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
