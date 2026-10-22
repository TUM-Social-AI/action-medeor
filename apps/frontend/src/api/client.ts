import type {
  CustomColumnRequest,
  ErpMatch,
  ExtractedItem,
  HomeResponse,
  ImportProgress,
  ImportFileType,
  ItemUpdate,
  ManualItemCreate,
  MatchingResponse,
  OfferResponse,
  PartnerDetails,
  PartnerUpdate,
  RecentImport,
  ReviewResponse,
  SummaryResponse,
  TrendsResponse,
} from './types';
import { requestJson } from './http';

export function getHome() {
  return requestJson<HomeResponse>('/api/home');
}

export function getImportProgress(token: string) {
  return requestJson<ImportProgress>(`/api/imports/progress/${token}`);
}

export function getRecentImports() {
  return requestJson<RecentImport[]>('/api/imports/recent');
}

export function createImport(file: File, selectedSheets?: string[], progressToken?: string) {
  const formData = new FormData();
  formData.append('file', file);
  if (progressToken) formData.append('progress_token', progressToken);
  selectedSheets?.forEach(sheet => formData.append('selected_sheets', sheet));

  return requestJson<ReviewResponse>('/api/imports', {
    method: 'POST',
    body: formData,
  });
}

export function inspectImport(file: File) {
  const body = new FormData();
  body.append('file', file);
  return requestJson<{ sheets: { name: string; rows: number }[] }>('/api/imports/inspect', {
    method: 'POST', body,
  });
}

export function getReview(requestId: string) {
  return requestJson<ReviewResponse>(`/api/requests/${requestId}/review`);
}

export function updateItem(requestId: string, itemId: number, payload: ItemUpdate) {
  return requestJson<ExtractedItem>(`/api/requests/${requestId}/items/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function addManualItem(requestId: string, payload: ManualItemCreate) {
  return requestJson<ExtractedItem>(`/api/requests/${requestId}/items`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function removeManualItem(requestId: string, itemId: number) {
  return requestJson<void>(`/api/requests/${requestId}/items/${itemId}`, { method: 'DELETE' });
}

export function verifyItem(requestId: string, itemId: number) {
  return requestJson<ExtractedItem>(`/api/requests/${requestId}/items/${itemId}/verify`, {
    method: 'POST',
  });
}

export function updatePartner(requestId: string, payload: PartnerUpdate) {
  return requestJson<PartnerDetails>(`/api/requests/${requestId}/partner`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function confirmPartner(requestId: string) {
  return requestJson<PartnerDetails>(`/api/requests/${requestId}/partner/confirm`, {
    method: 'POST',
  });
}

/** label='' resets that column back to its default (removes the rename). */
export function updateColumnLabel(requestId: string, columnKey: string, label: string) {
  return requestJson<Record<string, string>>(`/api/requests/${requestId}/column-labels`, {
    method: 'PATCH',
    body: JSON.stringify({ columnKey, label }),
  });
}

/** Requests one more field to extract, after the fact - see ReviewItemsScreen's "Add column"
 * control. Re-parses the original file server-side and returns the full, updated review payload
 * (new attribute values merged into the existing items, availableColumns/attributeColumns
 * updated) rather than just the one new column, since every item can gain a value at once. */
/** Re-extract the request from another worksheet of its spreadsheet; manual rows are kept. */
export function selectWorksheet(requestId: string, sheet: string) {
  return requestJson<ReviewResponse>(`/api/requests/${requestId}/worksheet`, {
    method: 'POST',
    body: JSON.stringify({ sheet }),
  });
}

export function addCustomColumn(requestId: string, column: CustomColumnRequest) {
  return requestJson<ReviewResponse>(`/api/requests/${requestId}/custom-columns`, {
    method: 'POST',
    body: JSON.stringify(column),
  });
}

export function startMatching(requestId: string) {
  return requestJson<MatchingResponse>(`/api/requests/${requestId}/matching`, {
    method: 'POST',
  });
}

export function updateMatching(requestId: string, itemId: number, matchId: string) {
  return requestJson<{ itemId: number; matchId: string }>(
    `/api/requests/${requestId}/matching/${itemId}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ matchId }),
    },
  );
}

export function getSummary(requestId: string) {
  return requestJson<SummaryResponse>(`/api/requests/${requestId}/summary`);
}

export function createOffer(requestId: string) {
  return requestJson<OfferResponse>(`/api/requests/${requestId}/offer`, {
    method: 'POST',
  });
}

export function getTrends() {
  return requestJson<TrendsResponse>('/api/trends');
}

export function getFileType(fileName: string): ImportFileType {
  const extension = fileName.toLowerCase().split('.').pop();

  if (
    extension === 'pdf' ||
    extension === 'xlsx' ||
    extension === 'xls' ||
    extension === 'docx' ||
    extension === 'csv'
  ) {
    return extension;
  }

  throw new Error('Unsupported file type');
}

export function firstMatch(matches: Record<string, ErpMatch[]>, itemId: number) {
  return matches[String(itemId)]?.[0]?.id ?? '';
}

export function reviewWithAi(requestId: string) {
  return requestJson<ReviewResponse>(`/api/requests/${requestId}/ai-review`, { method: 'POST' });
}
