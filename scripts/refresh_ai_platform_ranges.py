"""Refresh the AI-platform address ranges in deploy/shared/edge.ts.

Calls from these ranges get the higher per-address rate limit (AI_LIMITER),
because every Claude user arrives through a few Anthropic addresses and every
ChatGPT user through OpenAI's connector addresses. Sources, both published by
the companies for firewall allowlists:

- Anthropic outbound (MCP tool calls): https://platform.claude.com/docs/en/api/ip-addresses
  (one fixed range, written below; it "will not change without notice")
- OpenAI ChatGPT connectors: https://openai.com/chatgpt-connectors.json

An address the lists miss simply keeps the normal limit, so a stale list is
harmless. Run, review the diff, then deploy the Workers:

    python3 scripts/refresh_ai_platform_ranges.py
"""
import datetime as dt, ipaddress, json, re, urllib.request
from pathlib import Path

EDGE = Path(__file__).resolve().parents[1] / "deploy/shared/edge.ts"
ANTHROPIC = ["160.79.104.0/21"]
OPENAI_URL = "https://openai.com/chatgpt-connectors.json"
BEGIN, END = "// BEGIN AI_PLATFORM_RANGES (scripts/refresh_ai_platform_ranges.py)", "// END AI_PLATFORM_RANGES"


def openai_ranges() -> list[str]:
    request = urllib.request.Request(OPENAI_URL, headers={"User-Agent": "1102tools-range-refresh/1 (+https://1102tools.com)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read())
    ranges = sorted({str(ipaddress.ip_network(p["ipv4Prefix"])) for p in data["prefixes"] if p.get("ipv4Prefix")},
                    key=lambda r: ipaddress.ip_network(r))
    if len(ranges) < 50:
        raise SystemExit(f"OpenAI's list has only {len(ranges)} ranges; refusing to shrink the allowlist.")
    return ranges


def block(ranges: list[str]) -> str:
    lines = []
    for i in range(0, len(ranges), 6):
        lines.append("  " + ", ".join(f'"{r}"' for r in ranges[i:i + 6]) + ",")
    return (f"{BEGIN}\n// Anthropic {', '.join(ANTHROPIC)}; OpenAI ChatGPT connectors ({len(ranges) - len(ANTHROPIC)} ranges), "
            f"fetched {dt.date.today().isoformat()}.\nconst AI_PLATFORM_RANGES = [\n" + "\n".join(lines) + f"\n];\n{END}")


def main():
    ranges = ANTHROPIC + [r for r in openai_ranges() if r not in ANTHROPIC]
    text = EDGE.read_text()
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"Markers not found in {EDGE}")
    EDGE.write_text(pattern.sub(lambda _: block(ranges), text))
    print(f"Wrote {len(ranges)} ranges to {EDGE}")


if __name__ == "__main__":
    main()
