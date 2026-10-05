import { ApiError } from '../../api/http';

export const MAX_CSV_BYTES = 25 * 1024 * 1024;

export function validateCatalogFiles(articles: File | null, translations: File | null): string | null {
  if (!articles || !translations) return 'Choose both article data and article translations CSV files.';
  for (const file of [articles, translations]) {
    if (!file.name.toLowerCase().endsWith('.csv')) return `${file.name} must be a CSV file.`;
    if (file.size === 0) return `${file.name} is empty.`;
    if (file.size > MAX_CSV_BYTES) return `${file.name} exceeds 25 MB.`;
  }
  return null;
}

export function catalogImportError(error: unknown): string {
  if (error instanceof ApiError && error.details && typeof error.details === 'object'
    && 'detail' in error.details && Array.isArray(error.details.detail)) {
    return error.details.detail.map((detail: { row?: number; field?: string; message?: string; msg?: string }) =>
      [detail.row ? `Row ${detail.row}` : null, detail.field, detail.message ?? detail.msg]
        .filter(Boolean).join(': '),
    ).join('\n');
  }
  return error instanceof Error ? error.message : 'Could not update the ERP catalogue.';
}
