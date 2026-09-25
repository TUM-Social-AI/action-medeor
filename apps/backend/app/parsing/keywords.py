"""Multilingual keyword dictionaries used to detect table columns and free-text fields.

Partner request files arrive in English, German, French, or Arabic (from IngestionScreen's
supported-languages note in the frontend). These keyword lists are intentionally small and
substring-matched rather than exhaustive dictionaries or NLP models - they only need to
recognize common header wording, not translate full sentences.

Matching is accent-insensitive: partners write both "Désignation" and "Designation", "Qté" and
"Qte", so headers and keywords are both folded to unaccented lowercase before comparison.
"""

import re
import unicodedata


def normalize(text: str) -> str:
    """Lowercase + strip accents, so "Désignation" and "Designation" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))

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

# A form can split the requested quantity across two columns instead of reporting one total: how
# many packs/boxes/cartons, and separately how many individual units make up one pack. Checked
# before the generic UNIT_KEYWORDS/QUANTITY_KEYWORDS below - "Units Per Pack" contains "unit" and
# would otherwise be misread as the generic unit-of-measure-text role, which both steals the
# wrong meaning AND (since it then already has a role) makes it unavailable as a candidate for
# the LLM quantity gap-fill (see llm_table_classifier.py) that exists for less predictable
# phrasings of this same pattern.
QUANTITY_PACKS_KEYWORDS = [
    "packs requested", "qty pack", "quantity pack", "number of packs", "boxes requested",
    "anzahl packungen", "colis demandés",
]
UNITS_PER_PACK_KEYWORDS = [
    "units per pack", "unit per pack", "units/pack", "unit/pack",
    "einheiten pro packung", "unités par colis", "unités par paquet",
]

# Order matters: match_column_role() returns the first role whose keywords appear in a header, so
# the more specific roles are checked first and "name" - the most generic, most collision-prone
# list ("article"/"item"/"produkt" are common words inside other compound headers too, e.g.
# "Article priority" contains "article") - is checked last, as a catch-all.
COLUMN_KEYWORDS: dict[str, list[str]] = {
    "quantity_packs": QUANTITY_PACKS_KEYWORDS,
    "units_per_pack": UNITS_PER_PACK_KEYWORDS,
    "quantity": QUANTITY_KEYWORDS,
    "unit": UNIT_KEYWORDS,
    "notes": NOTES_KEYWORDS,
    "priority": PRIORITY_KEYWORDS,
    "shelf_life": SHELF_LIFE_KEYWORDS,
    "translation": TRANSLATION_KEYWORDS,
    "name": NAME_KEYWORDS,
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

# A reference/SKU column ("Item number", "Artikelnummer", "SKU", "Code PUI") - real, useful data,
# but must never be confused with the item-name column. Checked before COLUMN_KEYWORDS so
# "Item number" doesn't fall through to the generic "item"-adjacent name matching. Patterns are
# matched against accent-folded text, so they never need accented variants.
ITEM_NUMBER_PATTERNS = [
    re.compile(r"item\s*[-.]?\s*(no\.?|number|#|id)\b"),
    re.compile(r"\bsku\b"),
    re.compile(r"artikel\s*[-.]?\s*(nr\.?|nummer)"),
    re.compile(r"material\s*[-.]?\s*(nr\.?|nummer|number)"),
    re.compile(r"\breference\b"),
    re.compile(r"reference\s*(no\.?|number)"),
    re.compile(r"\bcode\b"),
]

# Opens a supplier/procurement-quote block ("Supplier I", "Anbieter III", "Supplier code").
SUPPLIER_BLOCK_KEYWORDS = ["supplier", "anbieter", "fournisseur", "proveedor"]

# Columns belonging to a supplier's quote, or to action medeor's own order administration -
# never part of what the partner requested. Only applied *inside* a supplier block (see
# classify_columns), which is what makes ambiguous entries like "unit qty" safe to list: the
# identically-named request column sits before the block starts.
SUPPLIER_FIELD_KEYWORDS = [
    "offered", "on offer", "im angebot",
    "unit price", "total price", "ek_price", "prix", "preis",
    "availability", "disponibilit", "verfugbar",
    "delivery time", "lieferzeit", "delai",
    "manufacturing date", "expiry date", "date d'expiration", "haltbarkeitsdatum",
    "manufacturer", "fabricant", "hersteller",
    "country", "pays", "herkunftsland",
    "vendor",
    "pack size", "packaging", "qty pack", "unit qty",
]

# Marks a column as partner-request-side even when it appears after a supplier block - RFQ forms
# like Premiere Urgence's put the requester's own fields ("Article priority", "Quality assurance
# requirements", "Comments") *after* the block the supplier fills in.
REQUEST_SIDE_KEYWORDS = [
    "enquiry", "anfrage", "requested", "request", "demande", "desired",
    "priorit", "quality assurance", "assurance qualit",
    "additional document", "documentation additionnelle",
    "comment", "commentaire",
]


def match_item_number_column(header_text: str) -> bool:
    normalized = normalize(header_text)
    return any(pattern.search(normalized) for pattern in ITEM_NUMBER_PATTERNS)


def is_supplier_block_start(header_text: str) -> bool:
    normalized = normalize(header_text)
    return any(keyword in normalized for keyword in SUPPLIER_BLOCK_KEYWORDS)


def is_supplier_field(header_text: str) -> bool:
    normalized = normalize(header_text)
    return any(keyword in normalized for keyword in SUPPLIER_FIELD_KEYWORDS)


def is_request_side(header_text: str) -> bool:
    normalized = normalize(header_text)
    return any(keyword in normalized for keyword in REQUEST_SIDE_KEYWORDS)


# A bare row-ordinal column ("No", "Nr.", "#", "Pos"). Real, but redundant with the row numbering
# the review screen already shows, so it's dropped rather than surfaced as an extra column.
# Matched on exact equality, so a descriptive header like "No. of units" is unaffected.
ORDINAL_COLUMN_LABELS = {
    "no", "no.", "nr", "nr.", "n", "n°", "#", "pos", "pos.", "position",
    "s/n", "sn", "sl", "sr", "seq", "line", "line no", "zeile", "lfd. nr", "lfd nr",
}


def is_ordinal_column(header_text: str) -> bool:
    return normalize(header_text) in ORDINAL_COLUMN_LABELS


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

# Procurement priority-tier wording ("Prioritaire-Priority", "Standard", "Optionnel-Optional")
# found in a dedicated priority/article-priority *column* - distinct from PRIORITY_TOKENS, which
# scans free-running name/notes text for urgency language. Deliberately not merged into
# PRIORITY_TOKENS: "standard" and "optional" are common enough words in item descriptions
# ("standard gauze", "optional attachment") that reusing the same scanner against name/notes
# text would misfire. No bare "priority"/"priorité" token here either - a value like "Low
# priority" would otherwise match the wrong tier depending on dict order.
PROCUREMENT_PRIORITY_TOKENS: dict[str, str] = {
    "prioritaire": "high",
    "urgence": "critical",
    "alternative": "low",
    "optionnel": "low",
    "optional": "low",
    "standard": "medium",
}


def match_column_role(header_text: str) -> str | None:
    """Return the column role ('name', 'quantity', ...) whose keywords appear in header_text."""
    normalized = normalize(header_text)
    if not normalized:
        return None
    if match_item_number_column(header_text):
        return "item_number"
    # Check this before generic "item"/"article" name keywords. Avoid a bare substring
    # "type" so packaging/unit-type headers do not become product classifications.
    if normalized in {
        "type", "typ", "category", "categorie", "kategorie", "warengruppe",
        "product type", "item type", "article type", "artikeltyp",
        "product category", "item category", "article category", "artikelkategorie",
        "type de produit", "categorie de produit", "نوع", "نوع المادة",
    } or "medicine/equipment" in normalized:
        return "domain"
    for role, keywords in COLUMN_KEYWORDS.items():
        if any(normalize(keyword) in normalized for keyword in keywords):
            return role
    return None


def classify_columns(header_cells: list[str]) -> list[bool]:
    """Decide, per column, whether it describes what the partner requested.

    Layouts differ in where the supplier's section sits: the Anfrage trackers append it at the
    end, while Premiere Urgence's form sandwiches it between the request columns and the
    requester's own fields. So rather than cutting the row at the first supplier column, track
    whether we're inside a supplier block and let an explicitly request-side header close it.
    """
    in_supplier_block = False
    keep: list[bool] = []

    for cell in header_cells:
        text = cell.strip()
        if not text or is_ordinal_column(text):
            keep.append(False)
            continue

        if is_supplier_block_start(text):
            in_supplier_block = True
            keep.append(False)
            continue

        if in_supplier_block:
            if is_supplier_field(text):
                keep.append(False)
                continue
            if is_request_side(text):
                in_supplier_block = False
                keep.append(True)
                continue
            # Unrecognized while inside the block (order numbers, certificates, "Info Status"):
            # stay conservative and treat it as the supplier's/our own administration.
            keep.append(False)
            continue

        keep.append(True)

    return keep
