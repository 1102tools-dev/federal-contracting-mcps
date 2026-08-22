#!/usr/bin/env python3
"""Render docs/architecture.png from docs/architecture-source.html.

Why this exists
---------------
The rendered diagram and its HTML source used to drift, because the PNG was
produced by hand and nothing tied it to the source. That is how the caption came
to claim "124 tool calls across eight servers" after Acquisition.gov made it nine
servers and 129 tools. Regenerating from source is now one command, so the two
move together.

Usage
-----
    uv run --with playwright python scripts/render_architecture.py
    uv run --with playwright python scripts/render_architecture.py --check

--check renders to a temporary file and compares tool counts in the source
against the caption, without writing the PNG. It does not compare pixels, since
font rasterization differs across machines.

Requires Playwright and a local Chrome (channel="chrome"), matching the renderer
used for the website images.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "docs" / "architecture-source.html"
OUTPUT = REPO_ROOT / "docs" / "architecture.png"
SCALE = 2  # retina, matching the existing asset


def audit_source() -> list[str]:
    """The caption must agree with the tiles it sits above."""
    html = SOURCE.read_text(encoding="utf-8")
    errors: list[str] = []

    counts = [int(value) for value in re.findall(r">(\d+) TOOLS", html)]
    caption = re.search(r'<p class="path-note">([^<]*)', html)
    if caption is None:
        return ["architecture-source.html: no path-note caption found"]
    text = caption.group(1)

    claimed_tools = re.search(r"(\d+)\s+tools", text)
    if claimed_tools is None:
        errors.append(f"caption does not state a tool count: {text!r}")
    elif int(claimed_tools.group(1)) != sum(counts):
        errors.append(
            f"caption claims {claimed_tools.group(1)} tools but the tiles sum to {sum(counts)}"
        )

    words = {"eight": 8, "nine": 9, "ten": 10, "eleven": 11}
    claimed_servers = re.search(r"across (\w+) servers", text)
    if claimed_servers is None:
        errors.append(f"caption does not state a server count: {text!r}")
    else:
        word = claimed_servers.group(1)
        if word not in words:
            errors.append(f"unrecognized server count word {word!r}")
        elif words[word] != len(counts):
            errors.append(
                f"caption claims {word} ({words[word]}) servers but there are {len(counts)} tiles"
            )

    if "tool calls" in text:
        errors.append("caption says 'tool calls'; these are tools, not calls")
    return errors


async def render(out_png: pathlib.Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        ctx = await browser.new_context(
            viewport={"width": 1800, "height": 900},
            device_scale_factor=SCALE,
        )
        page = await ctx.new_page()
        await page.goto(SOURCE.as_uri(), wait_until="networkidle")
        await page.wait_for_timeout(400)  # let webfonts settle before capture
        out_png.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out_png), full_page=True)
        await browser.close()


async def main() -> None:
    check_only = "--check" in sys.argv[1:]
    errors = audit_source()
    if errors:
        print("architecture source is internally inconsistent:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    if check_only:
        print("architecture-source.html caption agrees with its tiles")
        return
    await render(OUTPUT)
    size = OUTPUT.stat().st_size
    print(f"rendered {OUTPUT.relative_to(REPO_ROOT)} ({size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
