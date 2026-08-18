import type {
  ErpMatch,
  ExtractedItem,
  HomeResponse,
  ImportFileType,
  ItemUpdate,
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

export function getRecentImports() {
  return requestJson<RecentImport[]>('/api/imports/recent');
}

export function createImport(file: File) {
  const formData = new FormData();
  formData.append('file', file);

  return requestJson<ReviewResponse>('/api/imports', {
    method: 'POST',
    body: formData,
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

  if (extension === 'pdf' || extension === 'xlsx' || extension === 'xls') {
    return extension;
  }

  throw new Error('Unsupported file type');
}

export function firstMatch(matches: Record<string, ErpMatch[]>, itemId: number) {
  return matches[String(itemId)]?.[0]?.id ?? '';
}
