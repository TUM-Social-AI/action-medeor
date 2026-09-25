import { requestJson } from './http';
import type { MatchCandidateV1, ProductDomain } from './matching/contracts';
import type { Priority, ReviewResponse } from './types';

export type RequestStatus = 'draft' | 'review' | 'matching_queued' | 'matching' | 'matching_failed' | 'match_review' | 'complete';
export type SavedRequest = {
  requestId: string;
  status: RequestStatus;
  sourceFile: string | null;
  partner: string;
  itemCount: number;
  createdAt: string;
};
export type SavedMatchLine = {
  itemId: number;
  name: string;
  quantity: number | null;
  unit: string;
  priority: Priority;
  domain: ProductDomain;
  status: 'pending' | 'running' | 'completed' | 'failed';
  error: string | null;
  runId: string | null;
  candidates: MatchCandidateV1[];
  selectedCandidateId: string | null;
  decisionType: string | null;
};
export type SavedMatching = {
  requestId: string;
  status: RequestStatus;
  completed: number;
  total: number;
  lines: SavedMatchLine[];
};
export type SavedSummary = {
  requestId: string;
  sourceFile: string;
  partner: string;
  items: Array<{
    itemId: number;
    requested: string;
    quantity: number | null;
    unit: string;
    domain: ProductDomain;
    decision: string;
    itemNumber: string | null;
    product: string | null;
    availability: string | null;
    warnings: string[];
    retrievalMethods: string[];
  }>;
  matchedCount: number;
  unmatchedCount: number;
};

export const createRequest = () => requestJson<SavedRequest>('/api/requests', { method: 'POST' });
export const listRequests = () => requestJson<SavedRequest[]>('/api/requests');
export const getRequest = (id: string) => requestJson<SavedRequest>(`/api/requests/${id}`);
export function uploadRequestFile(id: string, file: File) {
  const body = new FormData();
  body.append('file', file);
  return requestJson<ReviewResponse>(`/api/requests/${id}/file`, { method: 'POST', body });
}
export const startRequestMatching = (id: string) =>
  requestJson<SavedMatching>(`/api/requests/${id}/matching`, { method: 'POST' });
export const getRequestMatching = (id: string) =>
  requestJson<SavedMatching>(`/api/requests/${id}/matching`);
export const decideRequestMatch = (
  id: string,
  itemId: number,
  decision: { candidateId?: string; noMatch?: boolean; overrideReason?: string },
) => requestJson<SavedMatching>(`/api/requests/${id}/items/${itemId}/decision`, {
  method: 'POST',
  body: JSON.stringify(decision),
});
export const getRequestSummary = (id: string) =>
  requestJson<SavedSummary>(`/api/requests/${id}/summary`);
