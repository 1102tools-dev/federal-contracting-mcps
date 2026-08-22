from __future__ import annotations

import io
from contextlib import asynccontextmanager

import httpx
import pytest
from pypdf import PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

import acquisition_gov_mcp.server as server
from acquisition_gov_mcp._pacing import FederalApiPacer


def text_pdf(*pages: str) -> bytes:
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=letter)
    for page in pages:
        y = 740
        for line in page.splitlines():
            pdf.drawString(72, y, line)
            y -= 16
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


def blank_pdf() -> bytes:
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def index_bytes(fixtures):
    return (fixtures / "rfo-index.html").read_bytes()


@pytest.fixture
def part_bytes(fixtures):
    return (fixtures / "rfo-part-10.html").read_bytes()


def test_tool_inventory_and_strict_schemas():
    tools = server.mcp._tool_manager.list_tools()
    assert {tool.name for tool in tools} == {
        "list_rfo_parts",
        "get_rfo_part",
        "list_rfo_agency_deviations",
        "get_rfo_agency_deviation",
        "get_rfo_guidance",
    }
    assert all(tool.fn_metadata.arg_model.model_config.get("extra") == "forbid" for tool in tools)


@pytest.mark.parametrize("part", [0, 54, "abc", "10.5"])
def test_invalid_parts(part):
    with pytest.raises(ValueError, match="part"):
        server._validate_part(part)


def test_url_allowlist_rejects_ssrf_and_hostile_forms():
    for url in (
        "http://www.acquisition.gov/path",
        "https://127.0.0.1/path",
        "https://169.254.169.254/latest/meta-data",
        "https://www.acquisition.gov.evil.test/path",
        "https://user@www.acquisition.gov/path",
        "https://www.acquisition.gov:443/path",
    ):
        with pytest.raises(ValueError):
            server._validated_url(url)


def test_parse_index_preserves_duplicate_and_multi_part_entries(index_bytes):
    parts = server._parse_index(index_bytes, server.RFO_INDEX_URL)
    assert [item["part"] for item in parts] == [10, 12]
    assert parts[0]["issuance_date"] == "2025-05-02"
    assert parts[0]["updated_date"] == "2025-08-15"
    gsa = [d for item in parts for d in item["agency_deviations"] if d["agency"].startswith("General")]
    assert len(gsa) == 3
    assert len({d["source_id"] for d in gsa}) == 1


@pytest.mark.asyncio
async def test_list_parts_filters_agency_and_date(monkeypatch, index_bytes):
    async def fake_fetch(url, **kwargs):
        return index_bytes, "text/html", server.RFO_INDEX_URL

    monkeypatch.setattr(server, "_fetch_bytes", fake_fetch)
    result = await server.list_rfo_parts(part=10, agency="services", updated_since="2025-01-01")
    assert result["count"] == 1
    assert result["results"][0]["agency_deviation_count"] == 2


@pytest.mark.asyncio
async def test_list_deviations_requires_filter_and_surfaces_ambiguity(monkeypatch, index_bytes):
    with pytest.raises(ValueError, match="filter"):
        await server.list_rfo_agency_deviations()

    async def fake_fetch(url, **kwargs):
        return index_bytes, "text/html", server.RFO_INDEX_URL

    monkeypatch.setattr(server, "_fetch_bytes", fake_fetch)
    result = await server.list_rfo_agency_deviations(part=10)
    assert result["count"] == 3
    assert any("duplicate" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_model_part_section_and_cursor(monkeypatch, part_bytes):
    async def fake_fetch(url, **kwargs):
        return part_bytes, "text/html", url

    monkeypatch.setattr(server, "_fetch_bytes", fake_fetch)
    result = await server.get_rfo_part(10, section="Model deviation", max_characters=1000)
    assert "Agencies should conduct market research" in result["content"]
    assert "Practitioner resources" not in result["content"]
    assert result["source_kind"] == "model_deviation"
    assert "not operative" in result["warnings"][0]
    with pytest.raises(ValueError, match="cursor"):
        await server.get_rfo_part(10, cursor="bad")


@pytest.mark.asyncio
async def test_guidance_heading_is_allowlisted(monkeypatch, fixtures):
    body = (fixtures / "rfo-guidance.html").read_bytes()

    async def fake_fetch(url, **kwargs):
        return body, "text/html", url

    monkeypatch.setattr(server, "_fetch_bytes", fake_fetch)
    result = await server.get_rfo_guidance("faq", heading="Agency adoption")
    assert "Model deviation text applies" in result["content"]
    assert "Other guidance" not in result["content"]
    assert result["source_kind"] == "nonregulatory_guidance"


def test_pdf_text_dates_applicability_and_page_limits():
    body = text_pdf(
        "Issued: August 1, 2025\nEffective Date: October 1, 2025\nApplicability: This deviation applies to solicitations issued on or after October 1, 2025.",
        "Expiration Date: October 1, 2027\nSecond page text.",
    )
    text, status, warnings, fields, total, end = server._read_pdf(body, page_start=1, page_end=2)
    assert status == "complete" and warnings == []
    assert "[Page 2]" in text and total == 2 and end == 2
    assert fields["effective_date"] == "2025-10-01"
    assert fields["expiration_date"] == "2027-10-01"
    assert "Page 1:" in fields["applicability_text"]
    with pytest.raises(ValueError, match="page_start"):
        server._read_pdf(body, page_start=3, page_end=None)


def test_image_only_and_malformed_pdf_are_metadata_only():
    _, status, warnings, _, total, _ = server._read_pdf(blank_pdf(), page_start=1, page_end=1)
    assert status == "unextractable" and total == 1
    assert any("scanned" in warning for warning in warnings)
    _, status, warnings, _, total, _ = server._read_pdf(b"not-a-pdf", page_start=1, page_end=1)
    assert status == "error" and total == 0 and warnings


@pytest.mark.asyncio
async def test_get_deviation_resolves_only_current_index(monkeypatch, index_bytes):
    pdf = text_pdf("Date: August 1, 2025\nApplicability: Applies to GSA solicitations.")
    parsed = server._parse_index(index_bytes, server.RFO_INDEX_URL)
    source_id = parsed[0]["agency_deviations"][0]["source_id"]

    async def fake_fetch(url, **kwargs):
        if url == server.RFO_INDEX_URL:
            return index_bytes, "text/html", server.RFO_INDEX_URL
        return pdf, "application/pdf", url

    monkeypatch.setattr(server, "_fetch_bytes", fake_fetch)
    result = await server.get_rfo_agency_deviation(source_id)
    assert result["text_extraction_status"] == "complete"
    assert "[Page 1]" in result["page_numbered_text"]
    assert result["far_parts"] == [10, 12]
    assert len(result["duplicate_index_entries"]) == 2
    assert result["text_truncated"] is False
    assert result["returned_characters"] == result["total_extracted_characters"]
    with pytest.raises(ValueError, match="not present"):
        await server.get_rfo_agency_deviation("agency-deviation-00000000000000000000")


@pytest.mark.asyncio
async def test_get_deviation_enforces_output_length_limit(monkeypatch, index_bytes):
    pdf = text_pdf("Date: August 1, 2025\n" + "Applicability: Applies to GSA solicitations.\n" * 20)
    parsed = server._parse_index(index_bytes, server.RFO_INDEX_URL)
    source_id = parsed[0]["agency_deviations"][0]["source_id"]

    async def fake_fetch(url, **kwargs):
        if url == server.RFO_INDEX_URL:
            return index_bytes, "text/html", server.RFO_INDEX_URL
        return pdf, "application/pdf", url

    monkeypatch.setattr(server, "_fetch_bytes", fake_fetch)
    monkeypatch.setattr(server, "MAX_OUTPUT_CHARACTERS", 100)
    result = await server.get_rfo_agency_deviation(source_id)
    assert result["text_truncated"] is True
    assert result["returned_characters"] == 100
    assert result["total_extracted_characters"] > result["returned_characters"]
    assert any("smaller page range" in warning for warning in result["warnings"])


class NoWaitPacer:
    @asynccontextmanager
    async def request_slot(self):
        class Slot:
            diagnostics = {}
            cooldown_until = 0.0

            def observe_response(self, response):
                if response.headers.get("Retry-After"):
                    self.diagnostics["retry_after"] = response.headers["Retry-After"]

            def raise_if_rate_limited(self, response, *, service):
                if response.status_code == 429:
                    raise RuntimeError(
                        f"{service} rate limited the request. Retry-After={self.diagnostics.get('retry_after')!r}"
                    )

        yield Slot()


@pytest.mark.asyncio
async def test_hostile_redirect_is_rejected(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "https://169.254.169.254/latest"})
    )
    client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_pacer", NoWaitPacer())
    with pytest.raises(ValueError, match="allowlist"):
        await server._fetch_bytes(server.RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=1000)
    await client.aclose()


@pytest.mark.asyncio
async def test_429_preserves_retry_after_without_retry(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "17"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_pacer", NoWaitPacer())
    with pytest.raises(RuntimeError, match="Retry-After='17'"):
        await server._fetch_bytes(server.RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=1000)
    assert calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_content_type_and_size_limits(monkeypatch):
    responses = iter(
        [
            httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{}"),
            httpx.Response(200, headers={"Content-Type": "text/html", "Content-Length": "2000"}, content=b"x"),
        ]
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: next(responses)))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_pacer", NoWaitPacer())
    with pytest.raises(RuntimeError, match="Content-Type"):
        await server._fetch_bytes(server.RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=1000)
    with pytest.raises(RuntimeError, match="exceeds"):
        await server._fetch_bytes(server.RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=1000)
    await client.aclose()


@pytest.mark.asyncio
async def test_python_transport_timeout_uses_bounded_curl_fallback(monkeypatch):
    def timeout_handler(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    calls = []

    async def fake_curl(url, *, max_bytes):
        calls.append((url, max_bytes))
        return (
            httpx.Response(200, headers={"Content-Type": "text/html"}),
            b"<html><main>fallback</main></html>",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_pacer", NoWaitPacer())
    monkeypatch.setattr(server, "_curl_once", fake_curl)
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(server, "_prefer_system_curl", False)
    body, content_type, _ = await server._fetch_bytes(
        server.RFO_INDEX_URL, allowed_types=("text/html",), max_bytes=1000
    )
    assert body.endswith(b"</html>") and content_type == "text/html"
    assert calls == [(server.RFO_INDEX_URL, 1000)]
    assert server._prefer_system_curl is True
    await client.aclose()


def test_pacer_configuration_rejects_invalid_override(tmp_path):
    pacer = FederalApiPacer(
        bucket="www.acquisition.gov",
        default_interval=3,
        environment={"FEDERAL_API_MIN_INTERVAL_SECONDS": "nan"},
        pacing_dir=tmp_path,
    )
    with pytest.raises(RuntimeError, match="finite"):
        pacer.configured_interval()
