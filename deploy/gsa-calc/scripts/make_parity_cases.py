"""Write deploy/gsa-calc/test/parity-cases.json, the parity case list.

Every tool and filter, ordering and sort, paging up to the 10,000 window,
exclude, 60 vendor names (from the private calc-name-sweep names.json, plus
the known hard ones), the common and retired SINs, suggest on all three
fields, every validation message, protocol calls in both eras, and
price_reasonableness_check rates placed at and around p25, p50 and p75.

With --db COPY.sqlite the price-check rates are placed at the copy's own
p25/p50/p75 for each title (read through the Worker's igce_benchmark, via
scripts/case-rates.ts); without it they are fixed guesses. Regenerate with the
copy of the night the cases will be recorded on.

    python3 deploy/gsa-calc/scripts/make_parity_cases.py [--db COPY.sqlite]

Each case is {name, tool, arguments} | {name, method, params} | {name, raw}
(test/parity-cases.json format, read by scripts/parity.py).
"""
import argparse, json, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "test/parity-cases.json"

COMMON_SINS = ["54151S", "541611", "541715", "541330ENG", "541690", "561210FAC", "541511", "611430"]
RETIRED_SINS = ["541512", "541513", "541610", "541519"]
TITLES = ["Project Manager", "Senior Software Engineer", "Software Engineer", "Program Manager", "Systems Engineer",
          "Business Analyst", "Data Scientist", "Registered Nurse I", "Help Desk Specialist", "Network Engineer",
          "Cybersecurity Analyst", "Cyber Security Analyst", "Subject Matter Expert", "Technical Writer", "Database Administrator",
          "Administrative Assistant", "Engineer II", "Ocean Engineer I", "Graphic Designer", "Training Specialist"]
# 60 vendor names: the hard ones first, then names from calc-name-sweep's names.json (major, anc, safelist).
VENDORS = [
    "PACT, INC.", "SAIC", "CACI", "PALANTIR", "Science Applications", "booz", "Booz Allen Hamilton", "Leidos", "Accenture Federal",
    "Deloitte", "ICF", "Gartner", "MITRE", "Peraton", "General Dynamics", "Lockheed", "Northrop", "Raytheon", "ManTech",
    "Guidehouse", "KPMG", "Ernst", "IBM", "Unisys", "Maximus", "Tetra Tech", "AECOM", "Jacobs", "ABT ASSOCIATES", "ASRC FEDERAL",
    "AMENTUM", "ALION SCIENCE", "AMERICAN SYSTEMS", "AKIMA", "CHENEGA", "BOWHEAD", "CALISTA", "AHTNA", "ARCTIC SLOPE REGIONAL",
    "CHICKASAW NATION", "1901 GROUP", "ABT GLOBAL", "APTIM", "A2Z INC", "3A, LLC", "ACI TECHNOLOGIES, INC.", "IMPACT RESOURCES, INC",
    "APOGEE-SAIC CAPABILITIES INTEGRATOR, LLC", "ABSG CONSULTING INC", "ACATO INFORMATION MANAGEMENT, LLC", "5D INFORMATION MANAGEMENT, INC",
    "AAC INC.", "ACCOUNT CONTROL TECHNOLOGY INC.", "AC FIRST, LLC", "IT", "AB", "LLC", "inc", "Corporation", "Consulting",
]
assert len(VENDORS) == 60, len(VENDORS)
ORDERINGS = ["current_price", "labor_category", "vendor_name", "education_level", "min_years_experience", "next_year_price",
             "idv_piid", "business_size"]


def tool(name, tool_name, **arguments):
    return {"name": name, "tool": tool_name, "arguments": arguments}


def protocol_cases():
    call = lambda args: json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "sin_analysis", "arguments": args}})
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
    return [
        {"name": "initialize", "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "parity", "version": "1"}}},
        {"name": "initialize unknown protocol version", "method": "initialize", "params": {"protocolVersion": "2026-07-28", "capabilities": {}, "clientInfo": {"name": "parity", "version": "1"}}},
        {"name": "initialize without params", "method": "initialize"},
        {"name": "ping", "method": "ping"},
        {"name": "tools/list", "method": "tools/list"},
        {"name": "prompts/list", "method": "prompts/list"},
        {"name": "resources/list", "method": "resources/list"},
        {"name": "resources/templates/list", "method": "resources/templates/list"},
        {"name": "resources/read unknown", "method": "resources/read", "params": {"uri": "calc://nothing"}},
        {"name": "unknown method", "method": "tools/frobnicate", "params": {}},
        {"name": "notification", "method": "notifications/initialized", "notification": True},
        {"name": "tools/call without arguments", "method": "tools/call", "params": {"name": "sin_analysis"}},
        {"name": "unknown tool", "tool": "get_salary", "arguments": {}},
        {"name": "validation float-ness of JSON numbers", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"keyword_search","arguments":{"keyword":"nurse","page":1.0,"page_size":1E1,"price_min":5,"experience_min":2.0}}}'},
        {"name": "validation big integers", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"keyword_search","arguments":{"keyword":"nurse","page":123456789012345678901234567890}}}'},
        {"name": "validation float too large for an integer", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"filtered_browse","arguments":{"experience_min":1e20,"page":9.3e18}}}'},
        {"name": "validation huge integer price", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"filtered_browse","arguments":{"price_min":1000000000000000000000000000000}}}'},
        {"name": "tools/call with null arguments", "raw": '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"sin_analysis","arguments":null}}'},
        {"name": "string request id", "raw": call({"sin_code": "611430"}).replace('"id": 1', '"id": "req-1"')},
        {"name": "tools/list with cursor", "raw": '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"cursor":"abc"}}'},
        {"name": "prompts/get unknown", "raw": '{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{"name":"nothing"}}'},
        {"name": "request id 1.0 is a notification", "raw": '{"jsonrpc":"2.0","id":1.0,"method":"ping"}'},
        {"name": "request id true is a notification", "raw": '{"jsonrpc":"2.0","id":true,"method":"tools/list"}'},
        {"name": "request id null is a notification", "raw": '{"jsonrpc":"2.0","id":null,"method":"ping"}'},
        {"name": "big integer request id", "raw": '{"jsonrpc":"2.0","id":1180591620717411303424,"method":"ping"}'},
        {"name": "client response accepted", "raw": '{"jsonrpc":"2.0","id":1,"result":{}}'},
        {"name": "client error accepted", "raw": '{"jsonrpc":"2.0","id":1,"error":{"code":1,"message":"x"}}'},
        {"name": "initialize without client version", "raw": '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"x"}}}'},
        {"name": "tools/call without name", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"arguments":{}}}'},
        {"name": "tools/call list arguments", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sin_analysis","arguments":[]}}'},
        {"name": "duplicate argument keys, last wins", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sin_analysis","arguments":{"sin_code":"bad code","sin_code":"611430"}}}'},
        {"name": "invalid: malformed JSON", "raw": '{"jsonrpc":"2.0","id":1,'},
        {"name": "invalid: batch", "raw": '[{"jsonrpc":"2.0","id":1,"method":"ping"}]'},
        {"name": "invalid: jsonrpc 1.0", "raw": '{"jsonrpc":"2.0x","id":1,"method":"ping"}'},
        {"name": "invalid: params is a list", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":[1]}'},
        {"name": "invalid: NaN literal", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"filtered_browse","arguments":{"price_min":NaN}}}'},
        {"name": "invalid: lone surrogate in an argument", "tool": "keyword_search", "arguments": {"keyword": "nurse \ud800"}},
        {"name": "invalid: lone low surrogate in an argument", "tool": "suggest_contains", "arguments": {"field": "vendor_name", "term": "\udc00ab"}},
        {"name": "modern: lone surrogate in an argument", "modern": True, "tool": "keyword_search", "arguments": {"keyword": "\udc00\udc01 nurse"}},
        {"name": "numeric-looking extra argument names", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sin_analysis","arguments":{"sin_code":"611430","b":1,"10":2,"a":3}}}'},
        {"name": "unknown protocol header routes to 2026 rules", "method": "tools/list", "headers": {"mcp-protocol-version": "1999-01-01"}},
        {"name": "handshake protocol header stays on the handshake path", "method": "ping", "headers": {"mcp-protocol-version": "2025-06-18"}},
        {"name": "content-type text/plain", "method": "ping", "headers": {"content-type": "text/plain"}},
        {"name": "content-type missing", "method": "ping", "headers": {"content-type": None}},
        # MCP 2026-07-28
        {"name": "modern: server/discover", "modern": True, "method": "server/discover"},
        {"name": "modern: server/discover, string id, no clientInfo", "modern": True, "method": "server/discover", "params": {"_meta": meta}, "id": "disc-1"},
        {"name": "modern: tools/list", "modern": True, "method": "tools/list"},
        {"name": "modern: tools/list with cursor", "modern": True, "method": "tools/list", "params": {"cursor": "abc"}},
        {"name": "modern: prompts/list", "modern": True, "method": "prompts/list"},
        {"name": "modern: resources/list", "modern": True, "method": "resources/list"},
        {"name": "modern: resources/templates/list", "modern": True, "method": "resources/templates/list"},
        {"name": "modern: resources/read unknown", "modern": True, "method": "resources/read", "params": {"uri": "calc://x"}},
        {"name": "modern: prompts/get unknown", "modern": True, "method": "prompts/get", "params": {"name": "p"}},
        {"name": "modern: unknown tool", "modern": True, "tool": "get_salary", "arguments": {}},
        {"name": "modern: keyword_search", "modern": True, "tool": "keyword_search", "arguments": {"keyword": "project manager", "page_size": 5}},
        {"name": "modern: price check", "modern": True, "tool": "price_reasonableness_check", "arguments": {"labor_category": "Registered Nurse I", "proposed_rate": 60}},
        {"name": "modern: validation error", "modern": True, "tool": "sin_analysis", "arguments": {"sin_code": "54-151"}},
        {"name": "modern: vendor card", "modern": True, "tool": "vendor_rate_card", "arguments": {"vendor_name": "booz", "page_size": 3}},
        {"name": "modern: tools/call without name", "modern": True, "method": "tools/call", "params": {"arguments": {}}},
        {"name": "modern: tools/call list arguments", "modern": True, "method": "tools/call", "params": {"name": "sin_analysis", "arguments": []}, "headers": {"mcp-name": "sin_analysis"}},
        {"name": "modern: mcp-method mismatch", "modern": True, "method": "tools/list", "headers": {"mcp-method": "tools/call"}},
        {"name": "modern: mcp-name mismatch", "modern": True, "tool": "sin_analysis", "arguments": {"sin_code": "611430"}, "headers": {"mcp-name": "keyword_search"}},
        {"name": "modern: protocol header differs from _meta", "modern": True, "method": "tools/list", "params": {"_meta": {**meta, "io.modelcontextprotocol/protocolVersion": "2027-01-01"}}},
        {"name": "modern: unsupported protocol version", "modern": True, "method": "tools/list", "params": {"_meta": {**meta, "io.modelcontextprotocol/protocolVersion": "2027-01-01"}}, "headers": {"mcp-protocol-version": "2027-01-01"}},
        {"name": "modern: protocol version not a string", "modern": True, "method": "tools/list", "params": {"_meta": {**meta, "io.modelcontextprotocol/protocolVersion": 5}}},
        {"name": "modern: _meta missing", "modern": True, "method": "tools/list", "params": {"_meta": None}},
        {"name": "modern: _meta not an object", "modern": True, "method": "tools/list", "params": {"_meta": 5}},
        {"name": "modern: _meta without capabilities", "modern": True, "method": "tools/list", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}},
        {"name": "modern: _meta without either key", "modern": True, "method": "server/discover", "params": {"_meta": {"x": 1}}},
        {"name": "modern: capabilities with a bad roots value", "modern": True, "method": "tools/list", "params": {"_meta": {**meta, "io.modelcontextprotocol/clientCapabilities": {"roots": 5}}}},
        {"name": "modern: capabilities with unknown keys", "modern": True, "method": "tools/list", "params": {"_meta": {**meta, "io.modelcontextprotocol/clientCapabilities": {"x": 5, "experimental": {}}}}},
        {"name": "modern: clientInfo null", "modern": True, "method": "server/discover", "params": {"_meta": {**meta, "io.modelcontextprotocol/clientInfo": None}}},
        {"name": "modern: clientInfo without version", "modern": True, "method": "server/discover", "params": {"_meta": {**meta, "io.modelcontextprotocol/clientInfo": {"name": "x"}}}},
        {"name": "modern: ping is not a 2026 method", "modern": True, "method": "ping"},
        {"name": "modern: initialize is not a 2026 method", "modern": True, "method": "initialize", "params": {"protocolVersion": "2026-07-28", "capabilities": {}, "clientInfo": {"name": "x", "version": "1"}}},
        {"name": "modern: completion/complete has no handler", "modern": True, "method": "completion/complete", "params": {"ref": {"type": "ref/prompt", "name": "x"}, "argument": {"name": "a", "value": "b"}}},
        {"name": "modern: completion/complete bad params", "modern": True, "method": "completion/complete"},
        {"name": "modern: unknown method", "modern": True, "method": "foo/bar"},
        {"name": "modern: notification is rejected", "modern": True, "method": "notifications/initialized", "notification": True},
        {"name": "modern: request id 1.0", "modern": True, "method": "tools/list", "id": 1.0},
        {"name": "modern: listen without event-stream accept", "modern": True, "method": "subscriptions/listen", "params": {"notifications": {"toolsListChanged": True}}, "headers": {"accept": "application/json"}},
        {"name": "modern: listen with a non-object filter", "modern": True, "method": "subscriptions/listen", "params": {"notifications": 5}},
        {"name": "modern: listen without a filter", "modern": True, "method": "subscriptions/listen"},
        {"name": "modern: accept application/json only", "modern": True, "method": "server/discover", "headers": {"accept": "application/json"}},
        {"name": "modern: accept */*", "modern": True, "method": "server/discover", "headers": {"accept": "*/*"}},
        {"name": "modern: accept event-stream only", "modern": True, "method": "server/discover", "headers": {"accept": "text/event-stream"}},
        {"name": "modern: malformed JSON", "raw": "{", "headers": {"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/list"}},
        {"name": "modern: params is a list", "raw": '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":[]}', "headers": {"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/list"}},
    ]


def validation_cases():
    k = lambda name, **a: tool(f"validation: {name}", "keyword_search", **{"keyword": "nurse", **a})
    f = lambda name, **a: tool(f"validation: {name}", "filtered_browse", **a)
    return [
        tool("validation: keyword missing", "keyword_search"),
        tool("validation: keyword empty", "keyword_search", keyword="   "),
        tool("validation: keyword not a string", "keyword_search", keyword=5),
        tool("validation: keyword control characters", "keyword_search", keyword="nurse\tpractitioner"),
        tool("validation: keyword newline", "keyword_search", keyword="nurse\n"),
        tool("validation: keyword too long", "keyword_search", keyword="a" * 501),
        tool("validation: keyword 500 characters", "keyword_search", keyword="a" * 500),
        tool("validation: keyword path traversal", "keyword_search", keyword="../etc"),
        tool("validation: keyword angle bracket", "keyword_search", keyword="<script>"),
        tool("validation: keyword angle bracket slash", "keyword_search", keyword="a </b"),
        tool("validation: keyword Kelvin sign after bracket", "keyword_search", keyword="<\u212a"),
        tool("validation: keyword non-ASCII", "keyword_search", keyword="Caf\u00e9 Manager \u00fc"),
        k("page 0", page=0), k("page too big", page=100001), k("page_size 0", page_size=0), k("page_size 501", page_size=501),
        k("page window", page=21, page_size=500), k("page window edge", page=20, page_size=500), k("page string", page="2"),
        k("page float", page=2.5), k("page bool", page=True), k("page list", page="[1]"),
        k("experience_min negative", experience_min=-1), k("experience_max negative", experience_max=-2),
        k("experience min above max", experience_min=10, experience_max=5), k("experience string", experience_min="5"),
        k("price_min negative", price_min=-1), k("price_max zero", price_max=0), k("price_max negative zero", price_max="-0"),
        k("price min above max", price_min=200, price_max=100.5), k("price nan string", price_min="nan"),
        k("price inf string", price_max="Infinity"), k("price -inf string", price_min="-inf"), k("price text", price_min="abc"),
        k("price underscores", price_min="1_000"), k("price spaces", price_min=" 50 "), k("price bool", price_min=True),
        k("price list", price_min=[1]), k("price tiny", price_min=1e-05), k("price huge", price_max=1e16),
        k("education bad code", education_level="BS"), k("education empty pipe", education_level="BA||MA"),
        k("education trailing pipe", education_level="BA|"), k("education lowercase", education_level="ba"),
        k("education spaces", education_level=" BA | MA "), k("education blank", education_level="  "),
        k("education null string", education_level="null"), k("education list string", education_level='["BA"]'),
        k("worksite", worksite="Customer"), k("worksite blank", worksite="  "),
        k("sin bool", sin=True), k("sin float", sin=1.5), k("sin whole float", sin=541611.0), k("sin list", sin=[1]),
        k("sin too long", sin="1" * 21), k("sin punctuation", sin="54-151"), k("sin int", sin=541611), k("sin negative int", sin=-5),
        k("sin blank", sin="   "), k("sin json string", sin="[1]"),
        k("ordering bad", ordering="price"), k("ordering padded", ordering=" labor_category "), k("ordering blank", ordering="  "),
        k("sort upper", sort="ASC"), k("sort bad", sort="up"), k("sort null string", sort="null"),
        k("business_size bad", business_size="L"), k("business_size null string", business_size="null"),
        k("clearance bad", security_clearance="maybe"), k("exclude control", exclude="1\n2"), k("exclude too long", exclude="1|" * 300),
        k("exclude angle", exclude="<a"), k("extra argument", q="x"), k("two extra arguments", q="x", limit=5),
        f("no filters"), f("no filters but worksite", worksite="Virtual"), f("only blank filters", education_level=" ", sin=" "),
        tool("validation: exact value empty", "exact_search", field="labor_category", value=" "),
        tool("validation: exact field bad", "exact_search", field="sin", value="x"),
        tool("validation: exact missing value", "exact_search", field="vendor_name"),
        tool("validation: exact value control", "exact_search", field="labor_category", value="a\x00b"),
        tool("validation: exact sin not accepted", "exact_search", field="labor_category", value="Engineer", sin="54151S"),
        tool("validation: suggest one character", "suggest_contains", field="vendor_name", term="b"),
        tool("validation: suggest one character padded", "suggest_contains", field="vendor_name", term=" b "),
        tool("validation: suggest field bad", "suggest_contains", field="sin", term="54"),
        tool("validation: suggest too long", "suggest_contains", field="labor_category", term="x" * 501),
        tool("validation: suggest path traversal", "suggest_contains", field="labor_category", term="a/../b"),
        tool("validation: igce empty", "igce_benchmark", labor_category=""),
        tool("validation: igce price filter not accepted", "igce_benchmark", labor_category="nurse", price_min=5),
        tool("validation: igce education bad", "igce_benchmark", labor_category="nurse", education_level="XX"),
        tool("validation: price check zero", "price_reasonableness_check", labor_category="nurse", proposed_rate=0),
        tool("validation: price check negative", "price_reasonableness_check", labor_category="nurse", proposed_rate=-5),
        tool("validation: price check nan", "price_reasonableness_check", labor_category="nurse", proposed_rate="nan"),
        tool("validation: price check inf", "price_reasonableness_check", labor_category="nurse", proposed_rate="1e400"),
        tool("validation: price check string", "price_reasonableness_check", labor_category="nurse", proposed_rate="sixty"),
        tool("validation: price check missing rate", "price_reasonableness_check", labor_category="nurse"),
        tool("validation: price check empty title", "price_reasonableness_check", labor_category=" ", proposed_rate=50),
        tool("validation: vendor one character", "vendor_rate_card", vendor_name="b"),
        tool("validation: vendor angle bracket", "vendor_rate_card", vendor_name="<b>"),
        tool("validation: vendor ordering bad", "vendor_rate_card", vendor_name="booz", ordering="rate"),
        tool("validation: vendor page window", "vendor_rate_card", vendor_name="booz", page=101),
        tool("validation: sin_code empty", "sin_analysis", sin_code=" "),
        tool("validation: sin_code bool", "sin_analysis", sin_code=False),
        tool("validation: sin_code null", "sin_analysis", sin_code=None),
        tool("validation: sin_code missing", "sin_analysis"),
        tool("validation: sin_code page_size", "sin_analysis", sin_code="54151S", page_size=0),
        tool("validation: sin_code too long", "sin_analysis", sin_code="X" * 25),
    ]


def search_cases():
    cases = []
    for title in TITLES:
        cases.append(tool(f"keyword: {title}", "keyword_search", keyword=title, page_size=5))
    for i, field in enumerate(ORDERINGS):
        for sort in ("asc", "desc"):
            cases.append(tool(f"keyword ordering {field} {sort}", "keyword_search", keyword=TITLES[i % len(TITLES)],
                              ordering=field, sort=sort, page_size=10))
    cases += [
        tool("keyword: lowercase", "keyword_search", keyword="project manager", page_size=3),
        tool("keyword: upper", "keyword_search", keyword="PROJECT MANAGER", page_size=3),
        tool("keyword: wildcard", "keyword_search", keyword="proj*manager", page_size=3),
        tool("keyword: leading wildcard", "keyword_search", keyword="*analyst", page_size=3),
        tool("keyword: two letters", "keyword_search", keyword="qa", page_size=3),
        tool("keyword: one letter", "keyword_search", keyword="x", page_size=3),
        tool("keyword: punctuation", "keyword_search", keyword="Sr.", page_size=3),
        tool("keyword: apostrophe", "keyword_search", keyword="O'Reilly", page_size=3),
        tool("keyword: ampersand", "keyword_search", keyword="R&D", page_size=3),
        tool("keyword: plus", "keyword_search", keyword="C++", page_size=3),
        tool("keyword: slash", "keyword_search", keyword="A/V Technician", page_size=3),
        tool("keyword: colon", "keyword_search", keyword="Engineer 1: Sr. Naval Architect", page_size=3),
        tool("keyword: question mark", "keyword_search", keyword="?", page_size=3),
        tool("keyword: contract number", "keyword_search", keyword="47QRAA22D004N", page_size=3),
        tool("keyword: contract number lowercase", "keyword_search", keyword="47qrea21d001b", page_size=3),
        tool("keyword: vendor name", "keyword_search", keyword="PROXY PERSONNEL", page_size=3),
        tool("keyword: nothing matches", "keyword_search", keyword="zzzzqqqq xyzzy", page_size=3),
        tool("keyword: nurse with all filters", "keyword_search", keyword="nurse", education_level="BA|MA", experience_min=1,
             experience_max=10, price_min=30, price_max=120.5, business_size="S", security_clearance="no", sin="541611", page_size=5),
        tool("keyword: clearance yes", "keyword_search", keyword="engineer", security_clearance="yes", page_size=3),
        tool("keyword: clearance no", "keyword_search", keyword="engineer", security_clearance="no", page_size=3),
        tool("keyword: business O", "keyword_search", keyword="analyst", business_size="O", page_size=3),
        tool("keyword: education PHD", "keyword_search", keyword="scientist", education_level="PHD", page_size=3),
        tool("keyword: education TEC", "keyword_search", keyword="technician", education_level="TEC", page_size=3),
        tool("keyword: education HS", "keyword_search", keyword="clerk", education_level="HS", page_size=3),
        tool("keyword: education AA", "keyword_search", keyword="technician", education_level="AA", page_size=3),
        tool("keyword: experience max only", "keyword_search", keyword="analyst", experience_max=2, page_size=3),
        tool("keyword: experience exact", "keyword_search", keyword="analyst", experience_min=5, experience_max=5, page_size=3),
        tool("keyword: price min only", "keyword_search", keyword="analyst", price_min=150, page_size=3),
        tool("keyword: price max only", "keyword_search", keyword="analyst", price_max=40, page_size=3),
        tool("keyword: price exact", "keyword_search", keyword="nurse", price_min=28.9, price_max=28.9, page_size=3),
        tool("keyword: paging page 2", "keyword_search", keyword="nurse", page=2, page_size=10),
        tool("keyword: paging past the end", "keyword_search", keyword="Registered Nurse I", page=50, page_size=100),
        tool("keyword: paging at the window", "keyword_search", keyword="engineer", page=20, page_size=500),
        tool("keyword: paging window 100x100", "keyword_search", keyword="manager", page=100, page_size=100),
        tool("keyword: page_size 500", "keyword_search", keyword="nurse", page_size=500),
        tool("keyword: page_size 1", "keyword_search", keyword="nurse", page_size=1),
        tool("keyword: exclude", "keyword_search", keyword="Registered Nurse I", exclude="1710487800|1703111483", page_size=5),
        tool("keyword: exclude unknown ids", "keyword_search", keyword="Registered Nurse I", exclude="1|2|abc", page_size=5),
        tool("keyword: exclude padded", "keyword_search", keyword="Registered Nurse I", exclude=" 1710487800 ", page_size=5),
        tool("keyword: whole index phrase", "keyword_search", keyword="a", page_size=2),
        tool("exact: Registered Nurse I", "exact_search", field="labor_category", value="Registered Nurse I", education_level="BA", experience_min=1, page_size=6),
        tool("exact: Ocean Engineer I", "exact_search", field="labor_category", value="Ocean Engineer I", page_size=11),
        tool("exact: colon title", "exact_search", field="labor_category", value="Engineer 1: Sr. Naval Architect Sr. Marine Engineer Sr. Ocean Engineer", page_size=11),
        tool("exact: colon title MA", "exact_search", field="labor_category", value="Engineer 1: Sr. Naval Architect Sr. Marine Engineer Sr. Ocean Engineer", education_level="MA", page_size=11),
        tool("exact: colon vendor", "exact_search", field="vendor_name", value="Leidos, Inc.: Engineering", page_size=3),
        tool("exact: colon contract", "exact_search", field="idv_piid", value="47QRAA:1", page_size=3),
        tool("exact: Leidos title with colon", "exact_search", field="labor_category", value="Leidos, Inc.: Engineering Drafting 3", page_size=3),
        tool("exact: lowercase title", "exact_search", field="labor_category", value="registered nurse i", page_size=3),
        tool("exact: vendor", "exact_search", field="vendor_name", value="PROXY PERSONNEL LLC", page_size=5),
        tool("exact: vendor ordered by title", "exact_search", field="vendor_name", value="T47 INTERNATIONAL, INC.", ordering="labor_category", sort="desc", page_size=5),
        tool("exact: contract", "exact_search", field="idv_piid", value="47QRAA22D004N", page_size=5),
        tool("exact: engineer II filters", "exact_search", field="labor_category", value="Engineer II", experience_min=3, price_max=150, business_size="S", page_size=5),
        tool("exact: Project Manager page 3", "exact_search", field="labor_category", value="Project Manager", page=3, page_size=50),
        tool("exact: no match", "exact_search", field="labor_category", value="Zzz Not A Title", page_size=5),
        tool("exact: paged past the end", "exact_search", field="labor_category", value="Ocean Engineer I", page=3, page_size=5),
    ]
    for field, terms in {"labor_category": ["nurse", "Engineer 1", "project man", "cyber", "QA", "sr.", "data sci", "*analyst", "zzqq"],
                         "vendor_name": ["booz", "SAIC", "pact", "Leidos", "inc", "llc", "deloitte", "PALANTIR", "ab", "1st choice"],
                         "idv_piid": ["47QRAA", "47qrea", "GS-35F", "GS10F", "47QTCA", "D004N", "zz"]}.items():
        for term in terms:
            cases.append(tool(f"suggest: {field} {term}", "suggest_contains", field=field, term=term))
    cases.append(tool("suggest: padded term", "suggest_contains", field="vendor_name", term="  booz  "))
    browse = [
        ("education BA", {"education_level": "BA"}), ("education MA|PHD", {"education_level": "MA|PHD"}),
        ("experience 5+", {"experience_min": 5}), ("experience 0-2", {"experience_max": 2}), ("experience 3-7", {"experience_min": 3, "experience_max": 7}),
        ("price 50+", {"price_min": 50}), ("price under 25", {"price_max": 25}), ("price 100-100.5", {"price_min": 100, "price_max": 100.5}),
        ("price whole dollars", {"price_min": 100, "price_max": 100}), ("business S", {"business_size": "S"}), ("business O", {"business_size": "O"}),
        ("clearance yes", {"security_clearance": "yes"}), ("clearance no", {"security_clearance": "no"}),
        ("sin 541611", {"sin": "541611"}), ("sin int", {"sin": 541611}), ("sin lowercase", {"sin": "54151s"}), ("sin partial", {"sin": "5415"}),
        ("BA 5-15 years", {"education_level": "BA", "experience_min": 5, "experience_max": 15}),
        ("MA S cleared", {"education_level": "MA", "business_size": "S", "security_clearance": "yes"}),
        ("sin and price", {"sin": "54151S", "price_min": 80, "price_max": 120}),
        ("sin ordered by vendor desc", {"sin": "611430", "ordering": "vendor_name", "sort": "desc"}),
        ("sin ordered by next year price", {"sin": "541715", "ordering": "next_year_price"}),
        ("sin ordered by experience desc", {"sin": "541330ENG", "ordering": "min_years_experience", "sort": "desc"}),
        ("sin ordered by contract", {"sin": "561210FAC", "ordering": "idv_piid"}),
        ("sin ordered by business size", {"sin": "541690", "ordering": "business_size", "sort": "desc"}),
        ("sin ordered by education", {"sin": "541511", "ordering": "education_level"}),
        ("page 2", {"education_level": "PHD", "page": 2, "page_size": 25}),
        ("page past end", {"education_level": "PHD", "price_min": 900, "page": 40, "page_size": 250}),
        ("window edge", {"business_size": "S", "page": 20, "page_size": 500}),
        ("worksite", {"business_size": "S", "worksite": "Virtual"}),
    ]
    for name, args in browse:
        cases.append(tool(f"browse: {name}", "filtered_browse", **{"page_size": 5, **args}))
    for title in TITLES[:12]:
        cases.append(tool(f"igce: {title}", "igce_benchmark", labor_category=title))
    cases += [
        tool("igce: nurse BA 1+", "igce_benchmark", labor_category="Registered Nurse I", education_level="BA", experience_min=1),
        tool("igce: nurse BA|MA 3+", "igce_benchmark", labor_category="Registered Nurse I", education_level="BA|MA", experience_min=3),
        tool("igce: engineer on 541330ENG", "igce_benchmark", labor_category="Engineer", sin="541330ENG"),
        tool("igce: analyst cleared", "igce_benchmark", labor_category="Analyst", security_clearance="yes", business_size="O"),
        tool("igce: experience max", "igce_benchmark", labor_category="Help Desk", experience_max=3),
        tool("igce: wildcard", "igce_benchmark", labor_category="Sr*Engineer"),
        tool("igce: vendor phrase", "igce_benchmark", labor_category="Systems Engineering"),
        tool("igce: contract number", "igce_benchmark", labor_category="47QRAA22D004N"),
        tool("igce: nothing", "igce_benchmark", labor_category="zzqq none"),
        tool("igce: colon title", "igce_benchmark", labor_category="Engineer 1: Sr. Naval Architect Sr. Marine Engineer Sr. Ocean Engineer"),
        tool("igce: padded", "igce_benchmark", labor_category="  Ocean Engineer I  "),
    ]
    for sin in COMMON_SINS:
        cases.append(tool(f"sin: {sin}", "sin_analysis", sin_code=sin, page_size=5))
    for sin in RETIRED_SINS:
        cases.append(tool(f"sin retired: {sin}", "sin_analysis", sin_code=sin))
    cases += [
        tool("sin: int", "sin_analysis", sin_code=611430),
        tool("sin: lowercase", "sin_analysis", sin_code="541330eng", page_size=1),
        tool("sin: 541330EMI", "sin_analysis", sin_code="541330EMI", page_size=11),
        tool("sin: page_size 500", "sin_analysis", sin_code="611430", page_size=500),
        tool("sin: padded", "sin_analysis", sin_code=" 54151S "),
        tool("sin: unknown", "sin_analysis", sin_code="999999ZZ"),
    ]
    for vendor in VENDORS:
        cases.append(tool(f"vendor: {vendor}", "vendor_rate_card", vendor_name=vendor, page_size=5))
    cases += [
        tool("vendor paging: booz page 2", "vendor_rate_card", vendor_name="booz", page=2, page_size=50),
        tool("vendor paging: booz past end", "vendor_rate_card", vendor_name="booz", page=99, page_size=100),
        tool("vendor paging: by price desc", "vendor_rate_card", vendor_name="Leidos", ordering="current_price", sort="desc", page_size=10),
        tool("vendor paging: page_size 500", "vendor_rate_card", vendor_name="Deloitte", page_size=500),
        tool("vendor paging: by contract", "vendor_rate_card", vendor_name="PROXY PERSONNEL", ordering="idv_piid"),
        tool("vendor: not found", "vendor_rate_card", vendor_name="zzqq no such vendor"),
        tool("vendor: padded", "vendor_rate_card", vendor_name="  booz allen  ", page_size=3),
    ]
    return cases


def price_cases(rates):
    cases = []
    for title, (p25, p50, p75) in rates.items():
        for label, rate in [("p25", p25), ("p50", p50), ("p75", p75), ("below p25", round(p25 - 0.01, 2)),
                            ("above p75", round(p75 + 0.01, 2)), ("p50 + 0.01", round(p50 + 0.01, 2))]:
            cases.append(tool(f"price: {title} at {label}", "price_reasonableness_check", labor_category=title, proposed_rate=rate))
    cases += [
        tool("price: nurse BA 1+ (fixture)", "price_reasonableness_check", labor_category="Registered Nurse I", education_level="BA", experience_min=1, proposed_rate=60),
        tool("price: nurse BA|MA 3+ (fixture)", "price_reasonableness_check", labor_category="Registered Nurse I", proposed_rate=135, education_level="BA|MA", experience_min=3),
        tool("price: integer rate", "price_reasonableness_check", labor_category="Ocean Engineer I", proposed_rate=72),
        tool("price: exact low sample", "price_reasonableness_check", labor_category="Ocean Engineer I", proposed_rate=72.54),
        tool("price: no data", "price_reasonableness_check", labor_category="zzqq none", proposed_rate=50),
        tool("price: with sin", "price_reasonableness_check", labor_category="Project Manager", sin="541611", proposed_rate=150),
        tool("price: cleared", "price_reasonableness_check", labor_category="Program Manager", security_clearance="yes", proposed_rate=175.5),
        tool("price: string rate", "price_reasonableness_check", labor_category="Project Manager", proposed_rate="120.25"),
        tool("price: tiny rate", "price_reasonableness_check", labor_category="Project Manager", proposed_rate=0.01),
        tool("price: huge rate", "price_reasonableness_check", labor_category="Project Manager", proposed_rate=99999),
    ]
    return cases


# Titles whose price checks put rates at the percentiles (fixed guesses without --db).
PRICE_TITLES = {"Project Manager": (95.0, 120.0, 150.0), "Senior Software Engineer": (110.0, 135.0, 160.0),
                "Business Analyst": (75.0, 95.0, 120.0), "Help Desk Specialist": (40.0, 55.0, 70.0),
                "Technical Writer": (60.0, 78.0, 95.0), "Database Administrator": (85.0, 105.0, 130.0),
                "Ocean Engineer I": (72.54, 72.54, 72.54), "Registered Nurse I": (63.92, 75.69, 105.18),
                "Network Engineer": (80.0, 100.0, 125.0), "Graphic Designer": (55.0, 70.0, 88.0)}


# Titles whose keyword population is one verified exact title with 20+ rates on night 1, so the price check
# gives a high/low verdict (found by checking every title with 20+ rates in the copy; only these 14 qualify:
# GSA's gram matching pools most titles with others). Rates sit at and around their percentiles.
VERDICT_TITLES = {"General Clerk II**": (34.698, 40.48, 50.06), "Warehouse Specialist**": (38.8, 44.62, 51.17),
                  "Information Technology Professional Services": (81.9744, 103.7518, 121.6307),
                  "General Clerk I**": (31.2994, 35.67, 42.7866), "Cloud Subject Matter Expert 1": (162.42, 192.88, 226.1308),
                  "Health IT Analyst III": (107.34, 134.01, 149.73), "General Maintenance Worker**": (52.93, 58.44, 67.8388),
                  "Engineering Technician II**": (49.63, 54.5087, 61.95), "Engineering Technician I**": (46.6443, 49.7181, 55.7),
                  "Forklift Operator**": (38.8, 46.64, 47.52), "GIS Specialist IV": (109.2, 127.71, 148.02),
                  "Senior Computer Systems Engineer/Architect": (132.66, 145.3899, 152.19),
                  "Engineering Technician III**": (60.0467, 62.6309, 68.28), "Senior Computer Hardware Engineer": (135.8164, 144.57, 151.25)}


def copy_rates(database, titles):
    """p25/p50/p75 for these titles from the copy (the Worker's igce_benchmark)."""
    out = subprocess.run(["node", "scripts/case-rates.ts", str(database), json.dumps(list(titles))],
                         cwd=HERE.parent, capture_output=True, text=True, check=True).stdout
    rates = json.loads(out)
    return {t: tuple(r) for t, r in rates.items() if None not in r}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", help="place price-check rates at this copy's percentiles")
    args = parser.parse_args()
    rates = {**PRICE_TITLES, **VERDICT_TITLES}
    if args.db:
        rates = copy_rates(Path(args.db).resolve(), rates)
    cases = protocol_cases() + validation_cases() + search_cases() + price_cases(rates)
    names = [c["name"] for c in cases]
    assert len(names) == len(set(names)), [n for n in names if names.count(n) > 1]
    OUT.write_text(json.dumps(cases, indent=1) + "\n")
    print(f"{len(cases)} cases written to {OUT}")


if __name__ == "__main__":
    main()
