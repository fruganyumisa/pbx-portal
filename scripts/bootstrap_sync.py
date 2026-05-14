#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

# Allow running as: python scripts/bootstrap_sync.py
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pbx_portal.sources import sync_freepbx_to_portal


def _parse_datetime(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime: {value}")


def _json_log(event, **fields):
    payload = {"event": event, **fields}
    print(json.dumps(payload, default=str), flush=True)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap PBX data sync in small batches. "
            "Each successful batch is saved to portal Postgres and updates sync_state."
        )
    )
    parser.add_argument("--start", required=True, help="Inclusive start datetime (e.g. 2026-05-13T00:00:00)")
    parser.add_argument("--end", help="Inclusive end datetime (default: now UTC)")
    parser.add_argument(
        "--batch-minutes",
        type=int,
        default=60,
        help="Batch size in minutes (default: 60)",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Sleep between batches to reduce PBX load (default: 0)",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with next batch on failure instead of exiting immediately",
    )
    args = parser.parse_args()

    start = _parse_datetime(args.start)
    end = _parse_datetime(args.end) if args.end else datetime.utcnow()
    batch_minutes = max(int(args.batch_minutes or 60), 1)
    sleep_seconds = max(float(args.sleep_seconds or 0), 0.0)

    if start >= end:
        _json_log("invalid_range", start=start.isoformat(), end=end.isoformat())
        return 2

    cursor = start
    batch_index = 0
    total_calls_stored = 0
    total_calls_received = 0
    total_agent_updates = 0
    had_error = False
    started_at = time.time()

    _json_log(
        "bootstrap_sync_started",
        start=start.isoformat(),
        end=end.isoformat(),
        batch_minutes=batch_minutes,
        sleep_seconds=sleep_seconds,
    )

    while cursor < end:
        batch_index += 1
        batch_end = min(cursor + timedelta(minutes=batch_minutes), end)
        _json_log(
            "batch_started",
            batch=batch_index,
            start=cursor.isoformat(),
            end=batch_end.isoformat(),
        )
        try:
            result = sync_freepbx_to_portal(
                start=cursor,
                end=batch_end,
                fallback_start=cursor,
            )
        except Exception as exc:
            had_error = True
            _json_log(
                "batch_failed",
                batch=batch_index,
                start=cursor.isoformat(),
                end=batch_end.isoformat(),
                error=str(exc),
            )
            if not args.continue_on_error:
                break
        else:
            calls = result.get("calls") or {}
            agents = result.get("agents") or {}
            total_calls_stored += int(calls.get("stored") or 0)
            total_calls_received += int(calls.get("received") or 0)
            total_agent_updates += int(agents.get("inserted") or 0) + int(agents.get("updated") or 0)
            _json_log(
                "batch_completed",
                batch=batch_index,
                calls_received=calls.get("received", 0),
                calls_stored=calls.get("stored", 0),
                call_chunks=calls.get("chunks", 0),
                agents_synced=agents.get("synced"),
                partial=result.get("partial", False),
                warnings=result.get("warnings", []),
            )
        cursor = batch_end
        if cursor < end and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    elapsed = round(time.time() - started_at, 2)
    _json_log(
        "bootstrap_sync_finished",
        completed_until=cursor.isoformat(),
        requested_end=end.isoformat(),
        batches=batch_index,
        elapsed_seconds=elapsed,
        total_calls_received=total_calls_received,
        total_calls_stored=total_calls_stored,
        total_agent_changes=total_agent_updates,
        ok=(not had_error and cursor >= end),
    )
    return 0 if (not had_error and cursor >= end) else 1


if __name__ == "__main__":
    sys.exit(main())
