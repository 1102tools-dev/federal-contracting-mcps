"""Real contracting workflows through MCP; raw answers retained for review."""
import asyncio
import json
import sys
from pathlib import Path

from federal_register_mcp.server import mcp

CASES = [
    ("What comment deadlines are coming up across government?", "open_comment_periods", {"limit": 100}),
    ("Which documents close October 10-13?", "search_documents", {"comment_date_gte": "2026-10-10", "comment_date_lte": "2026-10-13", "doc_types": ["RULE", "PRORULE", "NOTICE"], "per_page": 100}),
    ("What open comments are relevant to acquisition?", "open_comment_periods", {"term": "acquisition", "limit": 10}),
    ("What FAR Council comments are open?", "open_comment_periods", {"far_council": True, "limit": 20}),
    ("Show FAR Council final rules in 2025.", "search_documents", {"far_council": True, "doc_types": ["RULE"], "pub_date_gte": "2025-01-01", "pub_date_lte": "2025-12-31", "per_page": 100}),
    ("What happened in FAR Case 2023-008?", "far_case_history", {"docket_id": "FAR Case 2023-008"}),
    ("Show the procurement overhaul executive order.", "search_documents", {"executive_order_number": 14275}),
    ("Get proposed overhaul rule details and full-text links.", "get_document", {"document_number": "2026-19158"}),
    ("Fetch two rules in my order and show missing records.", "get_documents_batch", {"document_numbers": ["2026-19162", "2099-99999", "2026-19158"]}),
    ("How many SBA rules were published in 2025, by type?", "get_facet_counts", {"facet": "type", "agencies": ["small-business-administration"], "pub_date_gte": "2025-01-01", "pub_date_lte": "2025-12-31"}),
    ("Which defense filings are on public inspection?", "get_public_inspection", {"agency_filter": "defense-department", "limit": 20}),
    ("What is the DFARS agency slug?", "list_agencies", {"query": "defense acquisition"}),
]


async def main():
    answers = []
    for question, name, args in CASES:
        result = await mcp.call_tool(name, args)
        value = getattr(result, "structured_content", None)
        if value is None:
            value = json.loads(result.content[0].text)
        answers.append({"question": question, "tool": name, "args": args, "answer": value})
        print(name, "ok", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(answers, indent=2))
    broad = answers[0]["answer"]
    assert broad["complete"] is (broad["scanned"] >= broad["total_open"])
    if not broad["complete"]:
        assert "earlier" in broad["note"]
    assert answers[3]["answer"]["far_council"]["complete"]
    assert str(answers[6]["answer"]["results"][0]["executive_order_number"]) == "14275"
    assert answers[7]["answer"]["document_number"] == "2026-19158"
    batch = answers[8]["answer"]
    assert [d["document_number"] for d in batch["results"]] == ["2026-19162", "2026-19158"]
    assert batch["errors"]["not_found"] == ["2099-99999"]
    assert answers[10]["answer"]["filters_applied"]["includes_sub_agencies"]
    print("12 realistic workflow checks passed")


asyncio.run(main())
