"""Write parity/corpus.json: the requests the parity harness sends to both servers.

Each scenario fixes today's date, the operator key, the hourly upstream cap,
and the GSA Per Diem API responses (by request path after /rates/). The
same responses are served to the Python package (httpx MockTransport) and to
the Worker (mocked fetch), so the harness compares the two servers' logic,
not GSA. City responses for FY2027 are the package's real recorded fixtures;
the rest are synthetic, shaped like GSA's API and built from the bundled
files of a neighboring year, plus malformed and error responses.

    PYTHONPATH=servers/gsa-perdiem-mcp/src python deploy/gsa-perdiem/parity/build_corpus.py
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from gsa_perdiem_mcp import snapshot

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REAL = ROOT / "servers/gsa-perdiem-mcp/tests/fixtures/gsa_city"
# Not a real credential. Spaces and URL-special characters exercise the
# raw, quote(), and quote_plus() redaction variants.
KEY = "Parity Test+Key/0123456789="
MONTHS = [("Jan", "January"), ("Feb", "February"), ("Mar", "March"), ("Apr", "April"), ("May", "May"),
          ("Jun", "June"), ("Jul", "July"), ("Aug", "August"), ("Sep", "September"), ("Oct", "October"),
          ("Nov", "November"), ("Dec", "December")]


def entry(city, county, meals, values, **extra):
    months = [{"value": v, "number": i + 1, "short": s, "long": l}
              for i, ((s, l), v) in enumerate(zip(MONTHS, values))]
    out = {"months": {"month": months}, "meals": meals, "zip": None, "county": county, "city": city,
           "standardRate": "false"}
    out.update(extra)
    return out


def rates(state, year, entries):
    return {"request": None, "errors": None, "rates": [
        {"oconusInfo": None, "rate": entries, "state": state, "year": year, "isOconus": "false"}], "version": None}


def from_bundle(year: snapshot.Year, area, state):
    rec = year.area_rate(area, state)
    by_month = rec["lodging_by_month"]
    return entry(rec["destination"], "" if rec["is_standard_rate"] else rec["location_defined"], rec["meals"],
                 [by_month[s] for s, _ in MONTHS])


def ok(body, status=200, headers=None):
    # "1e400" in a JSON body: Python's json reads it as inf, JavaScript as Infinity.
    text = body if isinstance(body, str) else json.dumps(body).replace('"__1e400__"', "1e400")
    return {"status": status, "headers": headers or {"content-type": "application/json"}, "body": text}


def city_path(city, state, year):
    return f"city/{urllib.parse.quote(city, safe='')}/state/{state}/year/{year}"


def call(name, arguments=None, raw_arguments=None):
    if raw_arguments is not None:
        return '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": %s, "arguments": %s}}' % (
            json.dumps(name), raw_arguments)
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments or {}}})


def rpc(method, params=None, id_=1):
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


def real_city_fixtures():
    out = {}
    for f in sorted(REAL.glob("city_*.json")):
        # city_Crystal20City_state_VA_year_2027.json -> city/Crystal%20City/state/VA/year/2027
        parts = f.stem.split("_")
        city = parts[1].replace("20", "%20")
        out[f"city/{city}/state/{parts[3]}/year/{parts[5]}"] = ok(f.read_text())
    return out


def scenarios():
    y2021 = snapshot.load_year(2021)
    y2027 = snapshot.load_year(2027)
    va2021 = [from_bundle(y2021, i, "VA") for i in sorted(y2021.state_destination_ids("VA"))]
    va_std = from_bundle(y2021, snapshot.STANDARD, "VA")
    va_std["city"] = "Standard Rate"
    dc2021 = from_bundle(y2021, y2021.zip_areas("22201")[0][0], "VA")
    mie2021 = [{"total": t["total"], "breakfast": t["breakfast"], "lunch": t["lunch"], "dinner": t["dinner"],
                "incidental": t["incidental"], "FirstLastDay": t["first_last_day"]} for t in y2021.mie_tiers]

    out = []

    out.append({
        "name": "protocol and bundled lookups",
        "today": "2026-10-08",
        "requests": [
            rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "parity", "version": "1"}}),
            rpc("initialize", {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": {"name": "parity", "version": "1"}}),
            rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "parity", "version": "1"}}),
            rpc("tools/list"),
            rpc("ping"),
            rpc("prompts/list"),
            rpc("resources/list"),
            rpc("resources/templates/list"),
            rpc("no/such/method"),
            rpc("tools/list", id_="string-id"),
            call("no_such_tool", {}),
            rpc("tools/call", {"name": "get_data_status", "arguments": []}),
            rpc("tools/call", {"name": "get_data_status", "arguments": "x"}),
            rpc("tools/call", {"arguments": {}}),
            rpc("tools/call", {"name": 5}),
            rpc("tools/call"),
            rpc("tools/call", {"name": "get_data_status", "arguments": None}),
            '{"jsonrpc": "1.0", "id": 1, "method": "ping"}',
            '{"jsonrpc": "2.0", "method": "notifications/initialized"}',
            '{"jsonrpc": "2.0", "id": null, "method": "ping"}',
            '{"jsonrpc": "2.0", "id": 1.5, "method": "ping"}',
            '{"jsonrpc": "2.0", "id": 1, "method": 5}',
            '{"jsonrpc": "2.0", "id": 1}',
            '[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]',
            '"just a string"',
            '{not json',
            '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "lookup_city_perdiem", "arguments": {"city": "\\ud800", "state": "VA"}}}',
            call("get_data_status"),
            call("lookup_zip_perdiem", {"zip_code": "22201"}),
            call("lookup_zip_perdiem", {"zip_code": " 02101-1234 "}),
            call("lookup_zip_perdiem", {"zip_code": "01011"}),
            call("lookup_zip_perdiem", {"zip_code": "01011", "county": "Hampden"}),
            call("lookup_zip_perdiem", {"zip_code": "01011", "county": "hampshire county"}),
            call("lookup_zip_perdiem", {"zip_code": "01011", "county": "Nowhere"}),
            call("lookup_zip_perdiem", {"zip_code": "01054"}),
            call("lookup_zip_perdiem", {"zip_code": "13850", "county": "Susquehanna"}),
            call("lookup_zip_perdiem", {"zip_code": "10509"}),
            call("lookup_zip_perdiem", {"zip_code": "19003"}),
            call("lookup_zip_perdiem", {"zip_code": "00000"}),
            call("lookup_zip_perdiem", {"zip_code": "99501", "county": "Anchorage"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2021}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "2024"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2028}),
            call("lookup_zip_perdiem", {"zip_code": "2220"}),
            call("lookup_zip_perdiem", {"zip_code": "\u0662\u0662\u0662\u0660\u0661"}),
            call("lookup_state_rates", {"state": "VA"}),
            call("lookup_state_rates", {"state": " ca ", "fiscal_year": 2024}),
            call("lookup_state_rates", {"state": "DC"}),
            call("lookup_state_rates", {"state": "WY", "fiscal_year": 2021}),
            call("lookup_state_rates", {"state": "AK"}),
            call("lookup_state_rates", {"state": "XX"}),
            call("lookup_state_rates", {"state": "Virginia"}),
            call("lookup_state_rates", {"state": "V1"}),
            call("get_mie_breakdown"),
            call("get_mie_breakdown", {"fiscal_year": 2021}),
            call("get_mie_breakdown", {"fiscal_year": None}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "county": "Arlington"}),
            call("lookup_city_perdiem", {"city": "Cambridge", "state": "MA", "county": "Middlesex"}),
            call("lookup_city_perdiem", {"city": "Lowell", "state": "MA", "county": "Middlesex County"}),
            call("lookup_city_perdiem", {"city": "Sedona", "state": "AZ", "county": "Yavapai"}),
            call("lookup_city_perdiem", {"city": "Prescott", "state": "AZ", "county": "Yavapai", "fiscal_year": 2025}),
            call("lookup_city_perdiem", {"city": "Richmond", "state": "VA", "county": "Richmond"}),
            call("lookup_city_perdiem", {"city": "Saint Louis", "state": "MO", "county": "St. Louis city"}),
            call("lookup_city_perdiem", {"city": "Springfield", "state": "MA", "county": "Nowhere"}),
            call("lookup_city_perdiem", {"city": "Honolulu", "state": "HI"}),
            call("lookup_city_perdiem", {"city": "Boston/Cambridge", "state": "MA", "county": "Suffolk"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 3, "travel_month": "Oct"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 1}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": "2", "travel_month": "february"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 365, "travel_month": "SEPTEMBER", "fiscal_year": 2026}),
            call("estimate_travel_cost", {"city": "Chester", "state": "MA", "county": "Hampden", "num_nights": 4, "travel_month": " "}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "num_nights": 3, "travel_month": "Mayhem"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "num_nights": 0}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "num_nights": 366}),
            call("estimate_travel_cost", {"city": "Anchorage", "state": "AK", "num_nights": 2}),
            call("compare_locations", {"locations": [
                {"city": "Arlington", "state": "VA", "county": "Arlington"},
                {"city": "Sedona", "state": "AZ", "county": "Yavapai"},
                {"city": "Boise", "state": "XX"},
                {"state": "VA"},
                {"city": "Anchorage", "state": "AK"},
                {"city": "Wichita", "state": "KS", "county": "Sedgwick"},
                {"city": "Chester", "state": "MA", "county": "Hampden"},
                {"city": "Lowell", "state": "MA", "county": "Nowhere"},
            ], "fiscal_year": 2027}),
            call("compare_locations", {"locations": []}),
            call("compare_locations", {"locations": [{"city": "A", "state": "VA", "county": "Arlington"}] * 26}),
        ],
    })

    out.append({
        "name": "argument validation",
        "today": "2026-10-08",
        "requests": [
            call("lookup_zip_perdiem", {"zip_code": 22201}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2019}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "abc"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": " +2_027 "}),
            call("lookup_zip_perdiem", raw_arguments='{"zip_code": "22201", "fiscal_year": 2027.0}'),
            call("lookup_zip_perdiem", raw_arguments='{"zip_code": "22201", "fiscal_year": 2026.5}'),
            call("lookup_zip_perdiem", raw_arguments='{"zip_code": "22201", "fiscal_year": 99999999999999999999999}'),
            call("lookup_zip_perdiem", raw_arguments='{"zip_code": "22201", "fiscal_year": 1e300}'),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "999999999999999999999999999999"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": True}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "[2027]"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "null", "county": "null"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "2027.00"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "\u00a02027\u3000"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "x" * 80}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": "\u00e9" * 40 + "a"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "zip": "22202", "extra": [1, 2.5, None, True]}),
            call("lookup_zip_perdiem", {}),
            call("lookup_zip_perdiem", {"zip_code": None}),
            call("lookup_city_perdiem", {"city": 5, "state": True, "fiscal_year": {"a": 1}, "county": 7, "zz": "q"}),
            call("lookup_city_perdiem", {"city": "a\\b", "state": "VA"}),
            call("lookup_city_perdiem", {"city": "a/b..c", "state": "VA"}),
            call("lookup_city_perdiem", {"city": "  \t ", "state": "VA"}),
            call("lookup_city_perdiem", {"city": "x" * 101, "state": "VA"}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "county": "Fair\x00fax"}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "county": "x" * 81}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "county": "  "}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "\u00df"}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "v\u00e1"}),
            call("estimate_travel_cost", {"city": "a", "state": "VA", "num_nights": None}),
            call("estimate_travel_cost", {"city": "a", "state": "VA", "num_nights": 2, "travel_month": 5}),
            call("estimate_travel_cost", {"city": "a", "state": "VA", "travel_month": "Jan"}),
            call("compare_locations", {"locations": {"city": "a"}}),
            call("compare_locations", {"locations": "[{\"city\": 1.0, \"state\": \"VA\"}, 5, {\"x\": null}]"}),
            call("compare_locations", {"locations": "not json"}),
            call("compare_locations", {}),
            call("get_data_status", {"verbose": True}),
            call("get_mie_breakdown", {"fiscal_year": 2027.0001}),
            call("get_mie_breakdown", raw_arguments="null"),
            rpc("tools/call", {"name": "get_data_status"}),
        ],
    })

    city_fixtures = real_city_fixtures()
    out.append({
        "name": "city lookups through the GSA API (real FY2027 responses)",
        "today": "2026-10-08",
        "fixtures": city_fixtures,
        "requests": [
            call("lookup_city_perdiem", {"city": c, "state": s, "fiscal_year": 2027})
            for c, s in [("Abingdon", "VA"), ("Bethesda", "MD"), ("Boise", "ID"), ("Chester", "MA"),
                         ("Crystal City", "VA"), ("Fort Meade", "MD"), ("McLean", "VA"), ("Tysons", "VA"),
                         ("Xyzzyville", "VA"), ("Milton", "OH"), ("Gardiner", "MT")]
        ] + [
            call("compare_locations", {"locations": [
                {"city": "Milton", "state": "OH"}, {"city": "Gardiner", "state": "MT"},
            ], "fiscal_year": 2027}),
            call("estimate_travel_cost", {"city": "Milton", "state": "OH", "num_nights": 2, "fiscal_year": 2027}),
            call("estimate_travel_cost", {"city": "Gardiner", "state": "MT", "num_nights": 30, "travel_month": "Jul"}),
            call("lookup_city_perdiem", {"city": "mclean", "state": "va"}),
            call("lookup_city_perdiem", {"city": "Crystal-City", "state": "VA"}),
            call("estimate_travel_cost", {"city": "McLean", "state": "VA", "num_nights": 2, "fiscal_year": 2027}),
            call("estimate_travel_cost", {"city": "Tysons", "state": "VA", "num_nights": 5, "travel_month": "Jul"}),
            call("estimate_travel_cost", {"city": "Xyzzyville", "state": "VA", "num_nights": 3, "fiscal_year": 2027}),
            call("estimate_travel_cost", {"city": "Abingdon", "state": "VA", "num_nights": 1, "travel_month": "dec"}),
            call("compare_locations", {"locations": [
                {"city": "Bethesda", "state": "MD"}, {"city": "Boise", "state": "ID"},
                {"city": "McLean", "state": "VA"}, {"city": "Xyzzyville", "state": "VA"},
                {"city": "Honolulu", "state": "HI"}, {"city": "", "state": "VA"},
                {"city": "Abingdon", "state": "VA"}, {"city": "Nowhere Town", "state": "VA"},
            ], "fiscal_year": 2027}),
        ],
    })

    weird = rates("PA", 2028, [
        entry("State College ", "Centre", "70", ["150", " 1_60 ", "1.9e2", "abc", None, 0, -5, 175.9, "175", "", "null", True]),
        None,
        {"city": None, "county": "Nowhere", "meals": 50},
        entry("Standard Rate", None, 68, [110] * 12),
        {"city": 12.5, "county": 3, "meals": [], "months": {"month": {"short": "Jan", "value": 99}}},
        {"city": "Hershey", "county": "Dauphin", "meals": "__1e400__",
         "months": {"month": [{"short": "Jan", "value": "inf"}, {"short": 7, "value": 3}, {"value": 4}]}},
    ])
    single = {"rates": {"rate": entry("Philadelphia", "Philadelphia", 92, [200] * 12)}}
    missing_months = rates("NM", 2028, [entry("Taos", "Taos", 74, [None, None, 120, 120, 130, 130, 130, 130, 120, 120, 0, 0])])
    no_meals = rates("NM", 2028, [entry("Gallup", "McKinley", 0, [100] * 12)])
    overflow = rates("NM", 2028, [{"city": "Socorro", "county": "Socorro", "meals": 74,
                                   "months": {"month": [{"short": "Jan", "value": "__1e400__"}]}}])
    out.append({
        "name": "non-bundled fiscal years and malformed GSA data",
        "today": "2026-10-08",
        "fixtures": {
            "zip/22201/year/2020": ok(rates("VA", 2020, [dc2021])),
            "zip/22030/year/2020": ok(rates("VA", 2020, [dc2021, va_std])),
            "zip/99999/year/2020": ok(rates("VA", 2020, [])),
            "zip/19103/year/2028": ok(single),
            "state/VA/year/2020": ok(rates("VA", 2020, va2021 + [va_std])),
            "state/TX/year/2028": ok({"rates": []}),
            "state/PA/year/2028": ok(weird),
            "conus/mie/2020": ok({"mieData": mie2021[:3] + [
                {"total": "74", "breakfast": "18.5", "lunch": None, "dinner": "x", "incidental": True},
                {"total": 0, "FirstLastDay": None},
                {"total": "1_0.5e1", "breakfast": " 1e3 ", "lunch": "nan", "dinner": "-inf", "incidental": [], "FirstLastDay": "51"},
                "not a dict",
            ]}),
            "conus/mie/2028": ok([{"total": 80.25, "breakfast": 20}, {"total": 1.005}]),
            city_path("Arlington", "VA", 2020): ok(rates("VA", 2020, [dc2021, va_std])),
            city_path("State College", "PA", 2028): ok(weird),
            city_path("Philadelphia", "PA", 2028): ok(single),
            city_path("Taos", "NM", 2028): ok(missing_months),
            city_path("Gallup", "NM", 2028): ok(no_meals),
            city_path("Socorro", "NM", 2028): ok(overflow),
            city_path("Hershey", "PA", 2028): ok(weird),
            city_path("Pittsburgh", "PA", 2028): ok(rates("PA", 2028, [entry("Pittsburgh", "Allegheny", 80, [180] * 12),
                                                                        entry("Philadelphia", "Philadelphia", 92, [200] * 12)])),
        },
        "requests": [
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2020}),
            call("lookup_zip_perdiem", {"zip_code": "22030", "fiscal_year": 2020}),
            call("lookup_zip_perdiem", {"zip_code": "22030", "fiscal_year": 2020, "county": "fairfax"}),
            call("lookup_zip_perdiem", {"zip_code": "22030", "fiscal_year": 2020, "county": "Loudoun"}),
            call("lookup_zip_perdiem", {"zip_code": "99999", "fiscal_year": 2020}),
            call("lookup_zip_perdiem", {"zip_code": "19103", "fiscal_year": 2028}),
            call("lookup_zip_perdiem", {"zip_code": "19104", "fiscal_year": 2028}),
            call("lookup_state_rates", {"state": "VA", "fiscal_year": 2020}),
            call("lookup_state_rates", {"state": "TX", "fiscal_year": 2028}),
            call("lookup_state_rates", {"state": "PA", "fiscal_year": 2028}),
            call("get_mie_breakdown", {"fiscal_year": 2020}),
            call("get_mie_breakdown", {"fiscal_year": 2028}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "fiscal_year": 2020, "county": "Arlington"}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "fiscal_year": 2020, "county": "Henrico"}),
            call("lookup_city_perdiem", {"city": "Arlington", "state": "VA", "fiscal_year": 2020}),
            call("lookup_city_perdiem", {"city": "State College", "state": "PA", "fiscal_year": 2028}),
            call("lookup_city_perdiem", {"city": "Philadelphia", "state": "PA", "fiscal_year": 2028}),
            call("lookup_city_perdiem", {"city": "Taos", "state": "NM", "fiscal_year": 2028}),
            call("lookup_city_perdiem", {"city": "Pittsburgh", "state": "PA", "fiscal_year": 2028}),
            call("lookup_city_perdiem", {"city": "Hershey", "state": "PA", "fiscal_year": 2028}),
            call("estimate_travel_cost", {"city": "Taos", "state": "NM", "num_nights": 2, "travel_month": "Jan", "fiscal_year": 2028}),
            call("estimate_travel_cost", {"city": "Taos", "state": "NM", "num_nights": 2, "travel_month": "Mar", "fiscal_year": 2028}),
            call("estimate_travel_cost", {"city": "Gallup", "state": "NM", "num_nights": 2, "fiscal_year": 2028}),
            call("estimate_travel_cost", {"city": "Socorro", "state": "NM", "num_nights": 2, "fiscal_year": 2028}),
            call("estimate_travel_cost", {"city": "State College", "state": "PA", "num_nights": 7, "travel_month": "Feb", "fiscal_year": 2028}),
            call("compare_locations", {"locations": [{"city": "Taos", "state": "NM"}, {"city": "Socorro", "state": "NM"}], "fiscal_year": 2028}),
            call("compare_locations", {"locations": [{"city": "Taos", "state": "NM"}, {"city": "Pittsburgh", "state": "PA"},
                                                     {"city": "Gallup", "state": "NM"}], "fiscal_year": 2028}),
        ],
    })

    long_text = "Bad gateway " + "x" * 600
    html = "<!DOCTYPE html><html><head><title>\n Not   Found </title></head><body><h1>Missing\tpage</h1></body></html>"
    echo = {"rates": [{"rate": [entry(f"Echo {KEY}", f"key={urllib.parse.quote(KEY, safe='')} plus={urllib.parse.quote_plus(KEY)}",
                                      70, [150] * 12)]}], "note": KEY}
    out.append({
        "name": "GSA API errors, redaction, and the response cache",
        "today": "2026-10-08",
        "fixtures": {
            city_path("Forbidden", "VA", 2027): ok('{"error": {"code": "API_KEY_INVALID"}}', 403),
            city_path("Missing", "VA", 2027): ok(html, 404, {"content-type": "text/html"}),
            city_path("Broken", "VA", 2027): ok(f"server error near {KEY}", 500, {"content-type": "text/plain"}),
            city_path("Limited", "VA", 2027): ok('{"error": "OVER_RATE_LIMIT"}', 429, {
                "content-type": "application/json", "retry-after": "120", "x-ratelimit-limit": "1000",
                "x-ratelimit-remaining": "0"}),
            city_path("Limited Two", "VA", 2027): ok("slow down", 429, {"content-type": "text/plain"}),
            city_path("Gateway", "VA", 2027): ok(long_text, 502, {"content-type": "text/plain"}),
            city_path("Teapot", "VA", 2027): ok("<html><body>no title here</body></html>", 418, {"content-type": "text/html"}),
            city_path("Html", "VA", 2027): ok(html, 200, {"content-type": "text/html; charset=utf-8"}),
            city_path("Empty", "VA", 2027): ok("", 200, {"content-type": "application/json"}),
            city_path("Null", "VA", 2027): ok("null"),
            city_path("Echo", "VA", 2027): ok(echo),
            city_path("Moved", "VA", 2027): ok("", 301, {"location": "https://example.com/elsewhere"}),
            city_path("Down", "VA", 2027): {"error": "connect"},
            city_path("Slow", "VA", 2027): {"error": "timeout"},
            city_path("Fort Meade", "MD", 2027): city_fixtures["city/Fort%20Meade/state/MD/year/2027"],
            city_path("O Fallon", "MO", 2027): ok(rates("MO", 2027, [entry("Standard Rate", "", 68, [110] * 12)])),
            "zip/22201/year/2028": ok("<html><title>Rate Limited</title></html>", 503, {"content-type": "text/html"}),
        },
        "requests": [
            call("lookup_city_perdiem", {"city": c, "state": "VA"})
            for c in ["Forbidden", "Missing", "Broken", "Limited", "Limited Two", "Gateway", "Teapot", "Html", "Empty",
                      "Null", "Null", "Echo", "Moved", "Down", "Slow"]
        ] + [
            call("lookup_city_perdiem", {"city": "Fort Meade", "state": "MD"}),
            call("lookup_city_perdiem", {"city": "Fort  Meade", "state": "MD"}),
            call("lookup_city_perdiem", {"city": "O'Fallon", "state": "MO"}),
            call("lookup_city_perdiem", {"city": "O\u2019Fallon", "state": "MO"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2028}),
            call("estimate_travel_cost", {"city": "Broken", "state": "VA", "num_nights": 2}),
            call("compare_locations", {"locations": [{"city": c, "state": "VA"} for c in
                                                     ["Gateway", "Limited", "Forbidden", "Echo", "Null"]]}),
        ],
    })

    out.append({
        "name": "hourly upstream budget",
        "today": "2026-10-08",
        "hourly_cap": 2,
        "fixtures": {city_path(c, "MD", 2027): city_fixtures["city/Fort%20Meade/state/MD/year/2027"]
                     for c in ["Fort Meade", "Odenton", "Laurel"]},
        "requests": [
            call("lookup_city_perdiem", {"city": "Fort Meade", "state": "MD"}),
            call("lookup_city_perdiem", {"city": "Odenton", "state": "MD"}),
            call("lookup_city_perdiem", {"city": "Laurel", "state": "MD"}),
            call("lookup_city_perdiem", {"city": "Fort Meade", "state": "MD"}),
            call("compare_locations", {"locations": [{"city": "Laurel", "state": "MD"}, {"city": "Odenton", "state": "MD"}]}),
            call("lookup_zip_perdiem", {"zip_code": "20755"}),
        ],
    })

    out.append({
        "name": "fiscal year boundary (September 30)",
        "today": "2026-09-30",
        "fixtures": {"zip/99999/year/2027": ok(rates("VA", 2027, []))},
        "requests": [
            call("get_data_status"),
            call("lookup_zip_perdiem", {"zip_code": "22201"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2027}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2028}),
            call("lookup_zip_perdiem", {"zip_code": "00000", "fiscal_year": 2027}),
            call("lookup_zip_perdiem", {"zip_code": "00000", "fiscal_year": 2027, "county": "Arlington"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 2, "travel_month": "Sep"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 2, "travel_month": "Oct"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 2, "travel_month": "Aug"}),
            call("estimate_travel_cost", {"city": "Boston", "state": "MA", "county": "Suffolk", "num_nights": 2}),
        ],
    })

    out.append({
        "name": "hosted key missing",
        "today": "2026-10-08",
        "key": "   ",
        "fixtures": city_fixtures,
        "requests": [
            call("get_data_status"),
            call("lookup_city_perdiem", {"city": "McLean", "state": "VA"}),
            call("lookup_zip_perdiem", {"zip_code": "22201"}),
            call("lookup_zip_perdiem", {"zip_code": "22201", "fiscal_year": 2020}),
            call("compare_locations", {"locations": [{"city": "McLean", "state": "VA"}, {"city": "Arlington", "state": "VA", "county": "Arlington"}]}),
        ],
    })
    out.append(sweep(y2027))
    return out


def sweep(y2027):
    """A deterministic sample across the bundled data: ZIPs (with and without
    county), every state, every M&IE table, and Census places by county."""
    requests = []
    for fy in (2027, 2024, 2021):
        year = snapshot.load_year(fy)
        zips = sorted(year.zips)
        requests += [call("lookup_zip_perdiem", {"zip_code": z, "fiscal_year": fy}) for z in zips[fy % 97::211]]
        requests.append(call("get_mie_breakdown", {"fiscal_year": fy}))
    states = sorted({d["state"] for d in y2027.destinations.values()} | {"WY", "ND", "DE"})
    requests += [call("lookup_state_rates", {"state": st, "fiscal_year": 2026}) for st in states]
    places = snapshot.places()
    for key in sorted(places)[::157]:
        state, name = key.split("|", 1)
        for county, _kind in places[key][:2]:
            requests.append(call("lookup_city_perdiem", {"city": name.title(), "state": state, "county": county.split("|", 1)[1]}))
    ambiguous = [z for z, e in sorted(y2027.zips.items()) if len(e) > 1][::23]
    for z in ambiguous:
        for area, st in y2027.zip_areas(z):
            county = "Nowhere" if area == snapshot.STANDARD else y2027.destinations[area]["location_defined"].split("/")[0].split(",")[0]
            requests.append(call("lookup_zip_perdiem", {"zip_code": z, "county": county}))
    return {"name": "sweep of the bundled data", "today": "2026-10-08", "requests": requests}


def main():
    corpus = {"key": KEY, "scenarios": scenarios()}
    (HERE / "corpus.json").write_text(json.dumps(corpus, indent=1, ensure_ascii=True) + "\n")
    print(sum(len(s["requests"]) for s in corpus["scenarios"]), "requests in", len(corpus["scenarios"]), "scenarios")


if __name__ == "__main__":
    main()
