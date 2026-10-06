"""Select complete source spans for large free-text documents, without clipping rows."""

import re

from app.parsing.types import ParsedLineItem


def text_review_source(text: str, item: ParsedLineItem) -> dict:
    if len(text) <= 16_000:
        return {"text": text}
    # Keep the full matched excerpt and its enclosing lines, plus nearby section context.
    # Character offsets refer to original text even when the extraction normalized whitespace.
    tokens = list(re.finditer(r"\S+", text))
    normalized = " ".join(match.group() for match in tokens)
    target = " ".join((item.excerpt or item.name).split())
    match = re.search(re.escape(target), normalized, re.IGNORECASE) if target else None
    offset = match.start() if match else -1
    if offset < 0:
        # No source alignment: don't substitute possibly invented extraction text as evidence.
        return {"text": text, "mappingUncertain": True}
    starts = []
    cursor = 0
    for token in tokens:
        starts.append((cursor, cursor + len(token.group()), token.start(), token.end()))
        cursor += len(token.group()) + 1
    begin = next(start for left, right, start, _ in starts if left <= offset < right)
    end_offset = match.end() - 1
    end = next(end for left, right, _, end in starts if left <= end_offset < right)
    line_start = text.rfind("\n", 0, begin) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    context_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
    return {"text": text[line_start:line_end], "context": text[context_start:line_start]}
