"""HTTP entry point for the two-file ERP catalog synchronization."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.contracts import (
    CatalogImportResponseV1,
    CatalogImportValidationError,
    CatalogItemViewV1,
)
from app.catalog.service import CatalogImportService
from app.db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["catalog"])
MAX_CSV_BYTES = 25 * 1024 * 1024


def get_catalog_import_service(
    session: AsyncSession = Depends(get_session),
) -> CatalogImportService:
    return CatalogImportService(session)


async def _read_csv(file: UploadFile) -> bytes:
    filename = file.filename or ""
    if not filename.casefold().endswith(".csv"):
        raise HTTPException(status_code=400, detail=f"{filename or 'File'} must be a CSV file")
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_CSV_BYTES:
            raise HTTPException(status_code=413, detail=f"{filename} exceeds 25 MB")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail=f"{filename} is empty")
    return b"".join(chunks)


@router.post(
    "/catalog-imports",
    response_model=CatalogImportResponseV1,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_import(
    article_data: UploadFile = File(..., description="Artikeldaten.csv"),
    article_translations: UploadFile = File(..., description="Artikeluebersetzungen.csv"),
    captured_at: datetime | None = Form(default=None),
    source_uri: str | None = Form(default=None),
    service: CatalogImportService = Depends(get_catalog_import_service),
) -> CatalogImportResponseV1:
    article_bytes = await _read_csv(article_data)
    translation_bytes = await _read_csv(article_translations)
    try:
        result = await service.import_files(
            article_data=article_bytes,
            translation_data=translation_bytes,
            article_filename=article_data.filename or "Artikeldaten.csv",
            translation_filename=article_translations.filename or "Artikeluebersetzungen.csv",
            captured_at=captured_at,
            source_uri=source_uri,
        )
    except CatalogImportValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[error.model_dump(mode="json") for error in exc.errors],
        ) from exc
    return result


@router.get("/catalog-imports/{import_id}", response_model=CatalogImportResponseV1)
async def get_catalog_import(
    import_id: UUID,
    service: CatalogImportService = Depends(get_catalog_import_service),
) -> CatalogImportResponseV1:
    result = await service.get_import(import_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Catalog import not found")
    return result


@router.get("/catalog-items/{item_number}", response_model=CatalogItemViewV1)
async def get_catalog_item(
    item_number: str,
    service: CatalogImportService = Depends(get_catalog_import_service),
) -> CatalogItemViewV1:
    result = await service.get_item(item_number)
    if result is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    return result
