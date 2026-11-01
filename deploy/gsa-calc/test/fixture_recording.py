"""Write a small recording (scripts/load_gsa_calc.py's format) from GSA's
answers in servers/gsa-calc-mcp/tests/fixtures (night of 2026-10-10):
records.jsonl.gz with every distinct hit, summary.json naming the night's
index, and manifest.jsonl + bodies/ holding the answers whose whole result
set was recorded (so the emulator over a copy of these records must
reproduce them exactly, scripts/compare-emulator.ts).

    python3 deploy/gsa-calc/test/fixture_recording.py OUT
    python3 scripts/load_gsa_calc.py build --rec OUT --local OUT.sqlite
"""
import gzip, hashlib, json, sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[3] / "servers/gsa-calc-mcp/tests/fixtures"


def main(out):
    out = Path(out)
    (out / "bodies").mkdir(parents=True, exist_ok=True)
    records, complete = {}, []
    for name in ("literal_colon_title_source_2026_10.json", "nurse_grade_source_2026_10.json"):
        for entry in json.loads((FIXTURES / name).read_text()).values():
            raw = entry["raw"]
            for hit in raw["hits"]["hits"]:
                records.setdefault(hit["_id"], hit["_source"])
            if raw["hits"]["total"]["value"] == len(raw["hits"]["hits"]):
                complete.append(((entry.get("url") or entry["source_url"]).split("?", 1)[1], raw))
    with gzip.open(out / "records.jsonl.gz", "wt", encoding="utf-8") as fh:
        for ident, source in records.items():
            fh.write(json.dumps({"_id": ident, "_source": source}) + "\n")
    index = next(iter({h["_index"] for _, raw in complete for h in raw["hits"]["hits"]}))
    (out / "summary.json").write_text(json.dumps({"index": index, "priced_records": len(records), "records": len(records),
                                                  "unresolved": 0, "lost_in_subslices": 0}) + "\n")
    with open(out / "manifest.jsonl", "w") as manifest:
        for n, (query, raw) in enumerate(complete, 1):
            body = json.dumps(raw).encode()
            (out / "bodies" / f"{n:05d}.json.gz").write_bytes(gzip.compress(body))
            manifest.write(json.dumps({"n": n, "query": query, "status": 200, "sha256": hashlib.sha256(body).hexdigest(),
                                       "bytes": len(body), "index": index}) + "\n")
    print(f"{len(records)} records, {len(complete)} complete answers in {out}")


if __name__ == "__main__":
    main(sys.argv[1])
