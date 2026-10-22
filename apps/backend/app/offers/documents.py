"""Consistent document labels for catalogue offers and matching provenance."""

from urllib.parse import unquote, urlparse


def offer_document_name(file_name: object, path: object, uri: str | None) -> str:
    for value in (file_name, path):
        if isinstance(value, str) and value.strip():
            name = value.rstrip("/").split("/")[-1]
            if name:
                return name
    return unquote(urlparse(uri or "").path).rstrip("/").split("/")[-1] or "Supplier offer"
