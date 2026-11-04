"""Read PDF text, using local OCR for image-only scanned pages."""

from app.core.config import get_settings


def extract_page_text(page) -> str:
    """Keep native text; render scanned pages only. Fail rather than silently lose data."""
    text = page.extract_text() or ""
    if text.strip() or not page.images:
        return text

    import pytesseract

    settings = get_settings()
    # Bound raster size as well as the Tesseract subprocess runtime.
    resolution = min(300, 72 * (20_000_000 / (page.width * page.height)) ** 0.5)
    image = page.to_image(resolution=resolution).original
    try:
        return pytesseract.image_to_string(
            image,
            lang=settings.ocr_languages,
            timeout=settings.ocr_timeout_seconds,
        )
    except (RuntimeError, OSError) as exc:
        raise RuntimeError(f"OCR failed on page {page.page_number}: {exc}") from exc
    finally:
        image.close()
