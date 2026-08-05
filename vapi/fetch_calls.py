#!/usr/bin/env python3
"""Fetch recent call transcripts from Vapi for reviewing/iterating on the prompt.

Usage:
    export VAPI_API_KEY=...
    python vapi/fetch_calls.py            # last 5 calls, summary only
    python vapi/fetch_calls.py --full 3   # last 3 calls, full transcript
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

VAPI_API_BASE = "https://api.vapi.ai"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="Number of recent calls to show")
    parser.add_argument("--full", action="store_true", help="Print full transcripts")
    args = parser.parse_args()

    api_key = os.environ.get("VAPI_API_KEY", "")
    if not api_key:
        print("ERROR: VAPI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(
        base_url=VAPI_API_BASE,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        resp = client.get("/call", params={"limit": args.limit})
        resp.raise_for_status()
        calls = resp.json()

    if not calls:
        print("No calls found yet.")
        return

    for call in calls:
        print("=" * 80)
        print(f"Call ID: {call.get('id')}")
        print(f"Started: {call.get('startedAt')}  Ended: {call.get('endedAt')}")
        print(f"Ended reason: {call.get('endedReason')}")
        print(f"Cost: {call.get('cost')}")
        summary = (call.get("analysis") or {}).get("summary")
        if summary:
            print(f"Summary: {summary}")
        if args.full:
            transcript = call.get("transcript") or "(no transcript available)"
            print("--- transcript ---")
            print(transcript)
        print()


if __name__ == "__main__":
    main()
