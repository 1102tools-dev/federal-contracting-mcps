#!/usr/bin/env python3
"""Paced live-probe harness for SAM.gov APIs.

Born from the 2026-08 round-10 live campaign (~230 calls over two nights,
zero throttles) after an unpaced full-suite run burned a key's entire daily
quota in 105 seconds. The discipline contract, enforced in code:

  - ONE request at a time; concurrency is structurally impossible.
  - A jittered wait before EVERY call (default 2-4 s; be generous).
  - A hard per-run budget; the counter is the ledger line count.
  - The FIRST 429 stops the run instantly. No retry. SAM throttle locks
    run to the next 00:00 UTC, so retrying only wastes the next day too.
  - Two consecutive 5xx stop the run. Timeouts get one retry, then are
    recorded as findings (some SAM endpoints HANG on bad input rather
    than erroring; that is data, not a transport problem).
  - Every call is appended to ledger.jsonl with the key masked.
  - Non-object JSON bodies (SAM returns bare strings on some errors) are
    captured, never crashed on.

Usage:
    SAM_AUDIT_KEY=SAM-... python paced_probe.py            # run example suite
    from paced_probe import Prober                          # or compose your own

The ledger and any response captures may contain FOUO data when run with a
federal-role key (points of contact etc.). Both are gitignored here; do not
publish them.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx

BASE = "https://api.sam.gov"


class StopRun(SystemExit):
    pass


class Prober:
    def __init__(self, key: str, *, budget: int = 40,
                 spacing: tuple[float, float] = (2.0, 4.0),
                 ledger: Path | None = None,
                 user_agent: str = "sam-live-audit/1.0 (paced single-thread)"):
        if not key:
            raise ValueError("no API key provided")
        self.key = key
        self.budget = budget
        self.spacing = spacing
        self.ledger = ledger or Path(__file__).resolve().parent / "ledger.jsonl"
        self.n = 0
        self._consec_5xx = 0
        self.client = httpx.Client(timeout=45, headers={"User-Agent": user_agent})

    # -- internals ---------------------------------------------------------
    def _mask(self, s: str) -> str:
        return s.replace(self.key, "[KEY]")

    def _log(self, rec: dict) -> None:
        with self.ledger.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def _stop(self, reason: str, code: int) -> None:
        self._log({"event": "STOP", "reason": reason, "calls_made": self.n})
        print(f"\n*** STOP: {reason} after {self.n} calls ***")
        raise StopRun(code)

    # -- public ------------------------------------------------------------
    def call(self, label: str, path: str, params: dict) -> dict:
        """Paced GET. Returns the parsed JSON body as a dict, always."""
        if self.n >= self.budget:
            self._stop("budget reached", 3)
        time.sleep(random.uniform(*self.spacing))
        self.n += 1
        try:
            r = self.client.get(BASE + path, params={**params, "api_key": self.key})
        except (httpx.TimeoutException, httpx.TransportError):
            time.sleep(20)
            try:
                r = self.client.get(BASE + path, params={**params, "api_key": self.key})
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self._log({"n": self.n, "label": label, "status": "timeout-x2",
                           "err": type(e).__name__,
                           "params": {k: v for k, v in params.items() if k != "api_key"}})
                print(f"[{self.n}/{self.budget}] {label} -> TIMEOUT x2 (endpoint hangs; recorded)")
                return {}
        try:
            body = r.json()
        except Exception:
            body = {"_nonjson": self._mask(r.text[:200])}
        if not isinstance(body, dict):
            body = {"_nondict_json": self._mask(str(body)[:200]),
                    "_nondict_type": type(body).__name__}
        rec = {"n": self.n, "label": label, "path": path,
               "params": {k: v for k, v in params.items() if k != "api_key"},
               "status": r.status_code, "totalRecords": body.get("totalRecords")}
        if r.status_code >= 400 or "_nondict_json" in body or "_nonjson" in body:
            rec["body_head"] = self._mask(json.dumps(body)[:250])
        self._log(rec)
        total = body.get("totalRecords")
        print(f"[{self.n}/{self.budget}] {label} -> {r.status_code}"
              f"{'' if total is None else f' total={total}'}")
        if r.status_code == 429:
            self._stop("429 received - key protected", 2)
        if 500 <= r.status_code < 600:
            self._consec_5xx += 1
            if self._consec_5xx >= 2:
                self._stop("two consecutive 5xx", 4)
        else:
            self._consec_5xx = 0
        return body

    def check(self, name: str, **fields) -> None:
        """Record a named verdict/observation in the ledger."""
        self._log({"check": name, **fields})

    # -- analysis helpers ----------------------------------------------------
    @staticmethod
    def first_list(body: dict):
        for k, v in (body or {}).items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return k, v
        return None, []

    @staticmethod
    def fp(record) -> str:
        return hashlib.md5(
            json.dumps(record, sort_keys=True, default=str).encode()
        ).hexdigest()[:10]

    @staticmethod
    def deep_find(obj, key):
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if cur.get(key):
                    return cur[key]
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        return None


if __name__ == "__main__":
    from sam_gov_suite import run  # noqa: PLC0415
    run(Prober(os.environ.get("SAM_AUDIT_KEY", ""),
               budget=int(os.environ.get("AUDIT_BUDGET", "20"))))
    sys.exit(0)
