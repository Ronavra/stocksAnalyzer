import asyncio
import httpx
import pytest
from app.providers import sec_documents
from app.research.guidance import extract_guidance


def read(html):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))) as client:
            return await sec_documents.visible_document(client, "https://www.sec.gov/Archives/edgar/data/1/a.htm")
    return asyncio.run(run())


def test_large_inline_image_is_discarded_but_visible_guidance_is_retained():
    html = '<img src="data:image/png;base64,' + 'A' * 8_100_000 + '"><p>Full-year 2026 guidance: adjusted EPS of $2 to $3.</p><script>Full-year 2026 guidance: EPS of $9 to $10.</script>'
    visible = read(html)
    assert len(visible) < 500 and "base64" not in visible and "$9" not in visible
    event = {"accession_number": "a", "filing_date": "2026-10-01", "observed_at": "2026-10-10T14:00:00Z", "published_at": "2026-10-01T14:00:00Z", "source_url": "https://www.sec.gov/Archives/edgar/data/1/a.htm"}
    assert extract_guidance(visible, 1, event)[0]["eps_guidance_low"] == 2


def test_download_and_visible_text_limits_remain_enforced(monkeypatch):
    monkeypatch.setattr(sec_documents, "MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(RuntimeError, match="download limit"):
        read("<p>" + "A" * 101 + "</p>")
    monkeypatch.setattr(sec_documents, "MAX_DOCUMENT_BYTES", 1000)
    monkeypatch.setattr(sec_documents, "MAX_VISIBLE_CHARS", 20)
    with pytest.raises(RuntimeError, match="visible-text limit"):
        read("<p>" + "A" * 21 + "</p>")
