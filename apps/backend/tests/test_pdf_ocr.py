"""Real PDF rendering with controlled recognition; no network or database required."""

import io
from unittest.mock import Mock

import pdfplumber
import pytest
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.core.config import get_settings
from app.offers.extraction import extract_offers, read_offer_document
from app.parsing.pdf_text import extract_page_text
from app.parsing.service import ParsingError, parse_upload


def mixed_pdf() -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(50, 750, "Native supplier context")
    pdf.showPage()
    image = Image.new("RGB", (1200, 300), "white")
    ImageDraw.Draw(image).text((30, 80), "Gauze 100 pcs", fill="black", font_size=48)
    pdf.drawImage(ImageReader(image), 50, 550, width=500, height=125)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


@pytest.fixture
def recognize(monkeypatch):
    import pytesseract

    mock = Mock(return_value="Gauze 100 pcs\n")
    monkeypatch.setattr(pytesseract, "image_to_string", mock)
    return mock


def test_native_text_skips_rendering_and_ocr(recognize):
    page = Mock(images=[{}])
    page.extract_text.return_value = "Existing text"
    assert extract_page_text(page) == "Existing text"
    page.to_image.assert_not_called()
    recognize.assert_not_called()


def test_blank_page_skips_ocr(recognize):
    page = Mock(images=[])
    page.extract_text.return_value = ""
    assert extract_page_text(page) == ""
    recognize.assert_not_called()


def test_scanned_request_uses_ocr_and_keeps_native_context(monkeypatch, recognize):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    try:
        result = parse_upload(filename="request.pdf", content=mixed_pdf())
        assert any("Gauze" in item.name and item.quantity == 100 for item in result.items)
        recognize.assert_called_once()
        assert recognize.call_args.kwargs == {"lang": "eng+deu+fra+ara", "timeout": 60}
    finally:
        get_settings.cache_clear()


def test_sharepoint_offer_reader_keeps_ocr_page_identity(recognize):
    chunks, warnings = read_offer_document(mixed_pdf(), "offer.pdf")
    assert not warnings
    text = "\n".join(chunk.text for chunk in chunks)
    assert "Native supplier context" in text
    assert '"page": 2' in text and "Gauze 100 pcs" in text
    recognize.assert_called_once()


def test_scanned_offer_evidence_is_checked_against_ocr_text(recognize):
    recognize.return_value = "Supplier A\nGauze 100 pcs\n"

    def llm(prompt, schema):
        assert "Gauze 100 pcs" in prompt
        return schema.model_validate({
            "warnings": [],
            "offers": [{
                "source_id": "page:2:line:1", "alternative_index": 1,
                "supplier": "Supplier A", "item_description": "Gauze 100 pcs",
                "offer_reference": None, "offer_date": None, "date_kind": None,
                "valid_until": None, "validity_text": None, "price_text": None,
                "price_amount": None, "currency": None, "price_basis": None,
                "price_conflict": False, "warnings": [],
                "evidence": [
                    {"field": "supplier", "location": "page:2", "excerpt": "Supplier A"},
                    {"field": "item_description", "location": "page:2",
                     "excerpt": "Gauze 100 pcs"},
                ],
            }],
        })

    result = extract_offers(mixed_pdf(), "offer.pdf", llm=llm)
    assert not result.failures
    assert result.chunks_succeeded == result.chunks_total
    assert len(result.offers) == 1
    assert result.offers[0].source_id == "page:2:line:1"
    assert not result.offers[0].warnings


@pytest.mark.parametrize("error", [RuntimeError("timeout"), OSError("missing engine")])
def test_ocr_failures_do_not_publish_partial_extractions(recognize, error):
    recognize.side_effect = error
    content = mixed_pdf()
    with pytest.raises(ParsingError, match="OCR failed on page 2"):
        parse_upload(filename="request.pdf", content=content)
    llm = Mock()
    result = extract_offers(content, "offer.pdf", llm=llm)
    assert result.failures and "OCR failed on page 2" in result.failures[0]
    assert not result.offers
    llm.assert_not_called()


def test_real_tesseract_recognizes_scanned_page(monkeypatch):
    """Run when the native engine is installed, in addition to deterministic pipeline tests."""
    import shutil

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract engine is not installed")
    monkeypatch.setenv("OCR_LANGUAGES", "eng+deu+fra+ara")
    get_settings.cache_clear()
    try:
        with pdfplumber.open(io.BytesIO(mixed_pdf())) as pdf:
            assert "Gauze 100 pcs" in extract_page_text(pdf.pages[1])
    finally:
        get_settings.cache_clear()
