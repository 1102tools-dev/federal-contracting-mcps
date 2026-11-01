"""Compare two deployed eCFR endpoints, such as the staging Worker and production.

Sends each tool call in test/parity-cases.json (the same bytes and headers
scripts/parity.py sends) to both endpoints and compares HTTP status and body.
Production answers from eCFR's latest date; staging answers from the D1
copy's date, so a pair whose bodies match once recent dates (the last 45 days)
are normalized is reported as a date-only difference.

    python3 deploy/ecfr/scripts/compare_live.py https://ecfr-mcp-staging.<account>.workers.dev \\
        https://ecfr.1102tools.com [--cases deploy/ecfr/test/parity-cases.json] [--only TEXT] [--json report.json]

Each endpoint gets at most one request every 3.5 seconds (production allows
20 a minute per address). Exits 1 if any case differs beyond dates.
"""
import argparse, datetime, difflib, json, re, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parity import CASES, pretty, request  # noqa: E402

DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
LIMITED = "limit of 20 calls per minute"


def normalize(body, today):
    """Recent dates (eCFR's latest date, the copy's date) as one placeholder."""
    def recent(m):
        try:
            day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return m.group(0)
        return "<recent date>" if abs((today - day).days) <= 45 else m.group(0)
    return DATE.sub(recent, body)


class Endpoint:
    def __init__(self, base, gap):
        self.url = base.rstrip("/").removesuffix("/mcp") + "/mcp"
        self.gap = gap
        self.last = 0.0

    def post(self, item):
        headers = {k: v for k, v in item["headers"].items() if k != "host"}
        headers["User-Agent"] = "1102tools-compare-live"
        headers["X-1102tools-Monitor"] = "1"
        for attempt in range(3):
            wait = self.last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            req = urllib.request.Request(self.url, data=item["body"].encode(), headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    status, body = response.status, response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as error:
                status, body = error.code, error.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError) as error:
                status, body = 0, f"request failed: {error}"
            if status == 429 or LIMITED in body:
                print(f"  rate limited by {self.url}; waiting 60 s", file=sys.stderr, flush=True)
                time.sleep(60)
                continue
            return {"status": status, "body": body}
        return {"status": status, "body": body}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("a", help="first endpoint (e.g. staging), with or without /mcp")
    parser.add_argument("b", help="second endpoint (e.g. https://ecfr.1102tools.com)")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--only", help="run only cases whose name contains this text")
    parser.add_argument("--all", action="store_true", help="also send the protocol cases (not only tool calls)")
    parser.add_argument("--gap", type=float, default=3.5, help="seconds between requests to one endpoint")
    parser.add_argument("--json", type=Path, help="write every case's verdict here")
    args = parser.parse_args(argv)

    cases = [c for c in json.loads(args.cases.read_text()) if args.all or "tool" in c]
    if args.only:
        cases = [c for c in cases if args.only in c["name"]]
    a, b = Endpoint(args.a, args.gap), Endpoint(args.b, args.gap)
    today = datetime.date.today()
    counts = {"identical": 0, "date-only": 0, "different": 0}
    report = []
    for case in cases:
        item = request(case)
        first, second = a.post(item), b.post(item)
        if (first["status"], first["body"]) == (second["status"], second["body"]):
            verdict = "identical"
        elif first["status"] == second["status"] and normalize(first["body"], today) == normalize(second["body"], today):
            verdict = "date-only"
        else:
            verdict = "different"
        counts[verdict] += 1
        report.append({"name": case["name"], "verdict": verdict, "status": [first["status"], second["status"]]})
        print(f"{verdict:10} {case['name']}", flush=True)
        if verdict == "different":
            sys.stdout.writelines(line + "\n" for line in list(difflib.unified_diff(
                pretty(normalize(first["body"], today)), pretty(normalize(second["body"], today)),
                args.a, args.b, lineterm="", n=1))[:40])
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    print(f"{len(cases)} cases: {counts['identical']} identical, {counts['date-only']} differ only in dates, "
          f"{counts['different']} different.")
    return 1 if counts["different"] else 0


if __name__ == "__main__":
    sys.exit(main())
