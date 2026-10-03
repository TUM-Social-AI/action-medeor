"""Conservative offer-validity arithmetic; source extraction remains literal."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_PERIOD = re.compile(
    r"\b(\d+)\s*(tage?n?|days?|wochen?|weeks?|monate?n?|months?|jahre?n?|years?)\b",
    re.IGNORECASE,
)
_VALIDITY = re.compile(
    r"gültig|gueltig|gültigkeit|bindefrist|angebotsfrist|valid|expiry|expires|in\s+\d+",
    re.IGNORECASE,
)
_OTHER_ANCHOR = re.compile(
    r"business|working|werktag|arbeitstag|receipt|received|erhalt|eingang|delivery|liefer|"
    r"order|bestellung|payment|zahlung|shelf|haltbar|product|produkt|\bEXP\b|today|heute|tomorrow|morgen",
    re.IGNORECASE,
)
_ANCHOR_CLAUSE = re.compile(r"\b(?:from|after|ab|nach|starting(?:\s+from)?)\s+(.+)", re.IGNORECASE)
_ISSUE_ANCHOR = re.compile(
    r"(?:(?:the\s+)?date\s+of\s+)?(?:issue|issuance|quotation|quote|offer(?:\s+date)?|sending|dispatch|sent)"
    r"|(?:dem\s+)?(?:angebotsdatum|ausstellungsdatum|versanddatum|versand|ausstellung)"
    r"|datum\s+dieses\s+angebots",
    re.IGNORECASE,
)


def resolve_validity(
    explicit: date | None,
    wording: str | None,
    anchor: date | None,
) -> tuple[date | None, str | None, list[str]]:
    if explicit is not None:
        return explicit, "explicit", []
    if not wording:
        return None, None, []
    periods = list(_PERIOD.finditer(wording))
    clause = _ANCHOR_CLAUSE.search(wording)
    if (
        _OTHER_ANCHOR.search(wording)
        or not _VALIDITY.search(wording)
        or len(periods) != 1
        or re.search(r"\d+\s*(?:or|oder|to|bis|-)\s*\d+", wording, re.IGNORECASE)
        or (clause and not _ISSUE_ANCHOR.fullmatch(clause[1].strip(" .:;")))
        or re.search(r"\bnot\s+valid|nicht\s+gültig", wording, re.IGNORECASE)
    ):
        return None, None, [f"Unresolved offer validity: {wording}"]
    if anchor is None:
        return None, None, ["Relative offer validity has no resolved offer date"]
    amount = int(periods[0][1])
    unit = periods[0][2].casefold()
    try:
        if unit.startswith(("tag", "day")):
            result = anchor + timedelta(days=amount)
        elif unit.startswith(("woch", "week")):
            result = anchor + timedelta(weeks=amount)
        else:
            months = amount * 12 if unit.startswith(("jahr", "year")) else amount
            absolute_month = anchor.year * 12 + anchor.month - 1 + months
            year, month = divmod(absolute_month, 12)
            month += 1
            result = date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))
        return result, "relative", []
    except (OverflowError, ValueError):
        return None, None, [f"Offer validity period out of range: {wording}"]
