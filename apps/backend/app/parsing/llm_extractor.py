"""LLM fallback extraction for documents whose layout isn't a clean, heuristically-parseable
table: free-form PDF pages and Word documents.

Used only when there's no reliable table structure to key column roles off of. One call per
document, not per line, to keep this bounded and cheap. See app.parsing.llm_client for provider
selection/dispatch.
"""

from pydantic import BaseModel, Field

from app.parsing.llm_client import LlmUnavailable, call_llm
from app.parsing.text_heuristics import build_item
from app.parsing.types import ParsedDocument, Priority

__all__ = ["LlmUnavailable", "extract_items_with_llm"]


class _LlmLineItem(BaseModel):
    name: str
    quantity: int | None = None
    unit: str = ""
    notes: str = ""
    priority: Priority = "medium"
    source_excerpt: str = ""
    # Self-reported per-field confidence (see prompt) - combined into one overall score in
    # extract_items_with_llm() rather than exposed as two numbers, since ParsedLineItem/
    # ExtractedItem only carry a single `confidence`.
    name_confidence: int = Field(ge=0, le=100)
    quantity_confidence: int = Field(ge=0, le=100)


class _LlmExtractionResult(BaseModel):
    items: list[_LlmLineItem]


_PROMPT = """\
You are extracting a medical supply request into structured line items from partner-submitted
document text. The text may be in English, German, French, or Arabic, and may be messy (OCR
artifacts, inconsistent formatting, free-running sentences instead of a table).

For each distinct requested item, extract:
- name: the FULL item identity exactly as specific as the source text makes it - dosage/
  concentration, form (tablet/capsule/ampoule/suspension...), gauge or size, and any
  presentation detail that distinguishes it from a similar item. Translate to English if the
  source language isn't English, but translating must never lose specificity: "AIGUILLE,
  stérile, Luer, 21 G, vert, IM" becomes "Needle, sterile, Luer, 21G, green, IM" - NEVER just
  "Needle". Two different lines in the source must never collapse to the same generic name; if
  you find yourself about to write a bare category noun (Needle, Syringe, Tube, Gauze...) for a
  line that has more identifying detail in the text, that detail belongs IN the name, not in notes.
- quantity: the requested amount as an integer, or null if not stated/illegible
- unit: the unit of measure (e.g. "caps", "vials", "bags"), translated to English, or "" if unclear
- notes: qualifiers that are NOT part of the item's identity (packaging preference, brand
  preference, certification requirements, etc.), translated to English
- priority: "critical" | "high" | "medium" | "low", inferred from urgency language, default "medium"
- source_excerpt: the original text snippet (in its original language) this item was extracted from
- name_confidence: integer 0-100, your confidence that "name" correctly and unambiguously
  identifies the specific item meant by the source text. Score lower for abbreviations that could
  refer to more than one product, garbled/OCR-damaged text, or a generic description standing in
  for a specific item. Score higher for a clear, specific, unambiguous mention.
- quantity_confidence: integer 0-100, your confidence in the "quantity" value itself. If quantity
  is null because the text genuinely never states an amount, that is a LOW-confidence situation
  (score 0-20) - being sure that no quantity was given is not the same as being sure of the
  quantity, and this field must reflect how well-determined the requested amount is, not how
  sure you are about your own null judgement. Score lower for hedged/approximate wording ("around",
  "about", "roughly", "as many as you can spare") and higher for an exact stated number.

Do not invent items that aren't in the text. If a field can't be determined, use null/"" rather
than guessing.

Document text:
---
{text}
---
"""

_MAX_INPUT_CHARS = 20_000  # keeps a single fallback call cheap and within a small model's comfort zone


def extract_items_with_llm(raw_text: str) -> ParsedDocument:
    text = raw_text.strip()
    if not text:
        raise LlmUnavailable("No text extracted from document to send to the LLM")

    prompt = _PROMPT.format(text=text[:_MAX_INPUT_CHARS])
    result = call_llm(prompt, _LlmExtractionResult)

    document = ParsedDocument(used_llm_fallback=True)
    for entry in result.items:
        document.items.append(
            build_item(
                name=entry.name,
                quantity=entry.quantity,
                unit=entry.unit,
                notes=entry.notes,
                priority=entry.priority,
                excerpt=entry.source_excerpt,
                confidence=_combine_confidence(entry.name_confidence, entry.quantity_confidence),
            )
        )
    document.rows_detected = len(document.items)
    return document


def _combine_confidence(name_confidence: int, quantity_confidence: int) -> int:
    """Simple average of the model's two self-reported scores, clamped defensively - structured
    output should already respect the schema's 0-100 bounds, but a model isn't obligated to."""
    combined = round((name_confidence + quantity_confidence) / 2)
    return max(0, min(100, combined))
