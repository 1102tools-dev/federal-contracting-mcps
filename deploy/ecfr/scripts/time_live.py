#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Time the same tool calls on two deployed eCFR endpoints (staging vs production).

Each call goes to both, twice (the second shows a warm cache), one request every
3.5 seconds per endpoint, under production's 20-a-minute limit.

    python3 deploy/ecfr/scripts/time_live.py https://ecfr-staging.1102tools.com https://ecfr.1102tools.com
"""

from __future__ import annotations

import json
import statistics
import sys
import time

import httpx

CALLS = [
    ("FAR 52.212-4 (common clause)", "lookup_far_clause", {"section_id": "52.212-4"}),
    ("FAR 52.219-14", "lookup_far_clause", {"section_id": "52.219-14"}),
    ("FAR 15.305", "get_cfr_content", {"section": "15.305"}),
    ("DFARS 252.204-7012", "lookup_far_clause", {"section_id": "252.204-7012"}),
    ("2 CFR 200.320", "get_cfr_content", {"title_number": 2, "section": "200.320"}),
    ("FAR Part 52, page 3", "get_cfr_content", {"part": "52", "page": 3}),
    ("FAR definition", "find_far_definition", {"term": "commercial product"}),
    ("sections in Part 19", "list_sections_in_part", {"part_number": "19"}),
    ("structure Part 15", "get_cfr_structure", {"part": "15"}),
    ("latest date", "get_latest_date", {}),
    ("rarely asked: 40 CFR 60.4", "get_cfr_content", {"title_number": 40, "section": "60.4"}),
    ("rarely asked: 7 CFR 1.1", "get_cfr_content", {"title_number": 7, "section": "1.1"}),
    ("rarely asked: 49 CFR 571.108 (long)", "get_cfr_content", {"title_number": 49, "section": "571.108"}),
    ("search (live on both)", "search_cfr", {"query": "small business set-aside", "title": 48, "per_page": 5}),
]
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
           "MCP-Protocol-Version": "2025-11-25", "User-Agent": "1102tools-timing-check"}


def main() -> int:
    a, b = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
    client = httpx.Client(timeout=90)
    last = {a: 0.0, b: 0.0}
    rows = []
    for label, tool, args in CALLS:
        times: dict[str, list[float]] = {a: [], b: []}
        for _ in range(2):
            for base in (a, b):
                wait = last[base] + 3.5 - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
                started = time.monotonic()
                r = client.post(f"{base}/mcp", headers=HEADERS, content=json.dumps(body))
                times[base].append(time.monotonic() - started)
                last[base] = time.monotonic()
                if r.status_code != 200 or '"isError":true' in r.text:
                    print(f"  {label} on {base}: {r.status_code} {r.text[:120]}")
        rows.append((label, times[a], times[b]))
        print(f"{label:40} new {times[a][0]:5.2f}s then {times[a][1]:5.2f}s | production {times[b][0]:5.2f}s then {times[b][1]:5.2f}s", flush=True)
    first_a = statistics.median(r[1][0] for r in rows)
    first_b = statistics.median(r[2][0] for r in rows)
    print(f"median first call: new {first_a:.2f}s, production {first_b:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
