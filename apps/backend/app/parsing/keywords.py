"""Multilingual keyword dictionaries used to detect table columns and free-text fields.

Partner request files arrive in English, German, French, or Arabic (from IngestionScreen's
supported-languages note in the frontend). These keyword lists are intentionally small and
substring-matched rather than exhaustive dictionaries or NLP models - they only need to
recognize common header wording, not translate full sentences.
"""

import re

# Column role -> list of header substrings (lowercased) that identify it, across languages.
# "item"/"artikel" are safe here only because match_column_role() checks ITEM_NUMBER_PATTERNS
# first - real request/quote trackers have an "Item number" (SKU) column that would otherwise
# collide with a bare "item" and steal the name role before "Product" is even considered.
NAME_KEYWORDS = [
    "item", "description", "product", "material", "medicine", "drug", "supply",
    "artikel", "bezeichnung", "produkt", "beschreibung", "medikament",
    "désignation", "produit", "article", "médicament",
    "الصنف", "المنتج", "الوصف", "الدواء",
]

QUANTITY_KEYWORDS = [
    "qty", "quantity", "amount", "count",
    "menge", "anzahl", "stückzahl",
    "quantité", "qté",
    "الكمية", "العدد",
]

UNIT_KEYWORDS = [
    "unit", "uom", "packaging",
    "einheit", "verpackung",
    "unité", "unite",
    "الوحدة",
]

NOTES_KEYWORDS = [
    "note", "remark", "comment", "specification", "spec",
    "bemerkung", "hinweis", "anmerkung",
    "remarque", "commentaire",
    "ملاحظات", "ملاحظة",
]

PRIORITY_KEYWORDS = [
    "priority", "urgency", "urgent",
    "priorität", "dringlichkeit",
    "priorité", "urgence",
    "الأولوية",
]

SHELF_LIFE_KEYWORDS = [
    "shelf life", "expiry", "expiration",
    "haltbarkeit", "mindesthaltbarkeit",
    "durée de conservation", "date de péremption",
    "تاريخ الصلاحية",
]

TRANSLATION_KEYWORDS = [
    "translation",
    "übersetzung",
    "traduction",
    "ترجمة",
]

COLUMN_KEYWORDS: dict[str, list[str]] = {
    "name": NAME_KEYWORDS,
    "quantity": QUANTITY_KEYWORDS,
    "unit": UNIT_KEYWORDS,
    "notes": NOTES_KEYWORDS,
    "priority": PRIORITY_KEYWORDS,
    "shelf_life": SHELF_LIFE_KEYWORDS,
    "translation": TRANSLATION_KEYWORDS,
}

# Request-level free-text field ("Besondere Informationen:" / "Special information:") some RFQ
# trackers carry above the item table. No sample file currently has priority-signalling text
# there, but when one does, its value becomes the fallback priority for every item in the file.
SPECIAL_INFO_KEYWORDS = [
    "besondere informationen",
    "special information",
    "special info",
    "informations spéciales",
    "informations speciales",
]

# A reference/SKU column ("Item number", "Artikelnummer", "SKU") - real, useful data, but must
# never be confused with the item-name column. Checked before COLUMN_KEYWORDS so "Item number"
# doesn't fall through to the generic "item"-adjacent name matching.
ITEM_NUMBER_PATTERNS = [
    re.compile(r"item\s*[-.]?\s*(no\.?|number|#|id)\b"),
    re.compile(r"\bsku\b"),
    re.compile(r"artikel\s*[-.]?\s*(nr\.?|nummer)"),
    re.compile(r"material\s*[-.]?\s*(nr\.?|nummer|number)"),
    re.compile(r"référence"),
    re.compile(r"reference\s*(no\.?|number)"),
]

# Marks the start of a supplier/procurement-quote block ("Supplier I", "Anbieter III") in RFQ
# tracker workbooks. Column scanning stops there - what a partner requested ends at this
# boundary; everything after is action medeor's own quote/order tracking for that line.
SUPPLIER_BLOCK_KEYWORDS = ["supplier", "anbieter", "fournisseur", "proveedor"]


def match_item_number_column(header_text: str) -> bool:
    lowered = header_text.strip().lower()
    return any(pattern.search(lowered) for pattern in ITEM_NUMBER_PATTERNS)


def is_supplier_block_start(header_text: str) -> bool:
    lowered = header_text.strip().lower()
    return any(keyword in lowered for keyword in SUPPLIER_BLOCK_KEYWORDS)

# Free-text unit tokens recognized when pulling a "<qty> <unit>" expression out of a sentence,
# e.g. "2000 pcs", "50 vials", "500 Beutel". Longest tokens should be checked first by callers.
UNIT_TOKENS = [
    "pcs", "pieces", "piece", "caps", "capsules", "tabs", "tablets", "vials", "vial",
    "bags", "bag", "boxes", "box", "sachets", "sachet", "pairs", "pair", "units", "unit",
    "ampoules", "ampoule", "bottles", "bottle", "kits", "kit", "rolls", "roll", "cartons",
    "carton", "packs", "pack", "sets", "set", "stück", "stk", "beutel", "packungen",
    "paquets", "boîtes", "sachets",
]

PRIORITY_TOKENS: dict[str, str] = {
    "critical": "critical",
    "urgent": "critical",
    "dringend": "critical",
    "high": "high",
    "hoch": "high",
    "élevé": "high",
    "medium": "medium",
    "mittel": "medium",
    "moyen": "medium",
    "low": "low",
    "niedrig": "low",
    "faible": "low",
}


def match_column_role(header_text: str) -> str | None:
    """Return the column role ('name', 'quantity', ...) whose keywords appear in header_text."""
    lowered = header_text.strip().lower()
    if not lowered:
        return None
    if match_item_number_column(lowered):
        return "item_number"
    for role, keywords in COLUMN_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return role
    return None
