"""Write deploy/gsa-calc/test/branch-cases.json: parity cases for the made-up
branch records in test/fixture-db.ts (branchRecords), which reach the tool
branches GSA's recorded answers don't. Run them over that copy:

    node deploy/gsa-calc/test/fixture-db.ts COPY.sqlite --branches
    uv run --frozen --python 3.12 --project servers/gsa-calc-mcp python deploy/gsa-calc/scripts/parity.py \\
        --db COPY.sqlite --cases deploy/gsa-calc/test/branch-cases.json
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "test/branch-cases.json"


def tool(name, tool_name, **arguments):
    return {"name": f"branch: {name}", "tool": tool_name, "arguments": arguments}


def main():
    cases = []
    # The 40 Verified Quantum Auditor prices: 60 + (37i mod 53) + (i mod 4)/4; rates around every percentile.
    prices = sorted(60 + ((i * 37) % 53) + (i % 4) * 0.25 for i in range(40))
    n = len(prices)
    for q in (10, 25, 50, 75, 90):
        p = prices[min(n - 1, q * n // 100)]
        for label, rate in (("at", p), ("below", round(p - 0.01, 2)), ("above", round(p + 0.01, 2))):
            cases.append(tool(f"verdict {label} p{q}", "price_reasonableness_check", labor_category="Verified Quantum Auditor", proposed_rate=rate))
    cases += [
        tool("verdict far below", "price_reasonableness_check", labor_category="verified quantum auditor", proposed_rate=1),
        tool("verdict far above", "price_reasonableness_check", labor_category="Verified Quantum Auditor", proposed_rate=500),
        tool("verdict at the average", "price_reasonableness_check", labor_category="Verified Quantum Auditor", proposed_rate=86.0),
        tool("verdict with filters", "price_reasonableness_check", labor_category="Verified Quantum Auditor", education_level="BA|MA", proposed_rate=80),
        tool("verdict small after filters", "price_reasonableness_check", labor_category="Verified Quantum Auditor", sin="541330ENG", experience_min=10, proposed_rate=80),
        tool("zero spread", "price_reasonableness_check", labor_category="Flat Rate Courier", proposed_rate=42.5),
        tool("zero spread above", "price_reasonableness_check", labor_category="Flat Rate Courier", proposed_rate=43),
        tool("vendor phrase", "price_reasonableness_check", labor_category="Rapid Courier", proposed_rate=40),
        tool("phrase in several titles", "price_reasonableness_check", labor_category="Courier", proposed_rate=40),
        tool("500-title cap", "price_reasonableness_check", labor_category="Gizmo Fitter", proposed_rate=80),
        tool("500-title cap igce", "igce_benchmark", labor_category="Gizmo Fitter"),
        tool("500-title cap keyword", "keyword_search", keyword="gizmo", page_size=3, ordering="labor_category", sort="desc"),
        tool("500-title cap sin", "sin_analysis", sin_code="541611", page_size=2),
        tool("500-title cap suggest", "suggest_contains", field="labor_category", term="gizmo fitter"),
        tool("igce verified", "igce_benchmark", labor_category="Verified Quantum Auditor", security_clearance="no"),
        tool("igce zero spread", "igce_benchmark", labor_category="Flat Rate Courier"),
        tool("vendor not a whole word", "vendor_rate_card", vendor_name="zorpx", page_size=10),
        tool("vendor whole word among several", "vendor_rate_card", vendor_name="zorp", page_size=5),
        tool("vendor substring of several", "vendor_rate_card", vendor_name="orp", page_size=5),
        tool("vendor acronym inside", "vendor_rate_card", vendor_name="ZORPL"),
        tool("vendor legal suffix inside", "vendor_rate_card", vendor_name="Zorp Industries, Inc."),
        tool("vendor paging", "vendor_rate_card", vendor_name="megazorpx", page=2, page_size=12),
        tool("vendor last page", "vendor_rate_card", vendor_name="megazorpx", page=3, page_size=12),
        tool("vendor past the end", "vendor_rate_card", vendor_name="megazorpx", page=4, page_size=12),
        tool("vendor by price desc", "vendor_rate_card", vendor_name="Gizmo Shop", ordering="current_price", sort="desc", page_size=4),
        tool("exact vendor", "exact_search", field="vendor_name", value="MEGAZORPX HOLDINGS", page_size=7, page=2),
        tool("suggest many vendors", "suggest_contains", field="vendor_name", term="gizmo"),
        tool("browse two orderings source", "filtered_browse", sin="54151S", ordering="education_level", sort="desc", page_size=5),
        tool("keyword exclude", "keyword_search", keyword="Flat Rate Courier", exclude="8000041|8000042", page_size=2),
    ]
    OUT.write_text(json.dumps(cases, indent=1) + "\n")
    print(f"{len(cases)} cases written to {OUT}")


if __name__ == "__main__":
    main()
