import { requestJson } from '../http';
import type {
  CreateInquiryRequest,
  ExtractedInquiryLineV1,
  ExtractionResultV1,
  InquiryLineUpdate,
  InquiryV1,
} from './contracts';

export interface ExtractionApi {
  createInquiry(request: CreateInquiryRequest): Promise<InquiryV1>;
  uploadFile(inquiryId: string, file: File): Promise<ExtractionResultV1>;
  getInquiry(inquiryId: string): Promise<InquiryV1>;
  getLines(inquiryId: string): Promise<ExtractedInquiryLineV1[]>;
  updateLine(lineId: string, update: InquiryLineUpdate): Promise<ExtractedInquiryLineV1>;
  validateLine(lineId: string): Promise<ExtractedInquiryLineV1>;
}

// Proposed Omar-facing API. Keeping it behind this interface allows paths or payloads
// to change after team review without affecting React components.
export const httpExtractionApi: ExtractionApi = {
  createInquiry(request) {
    return requestJson<InquiryV1>('/api/v1/inquiries', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  uploadFile(inquiryId, file) {
    const body = new FormData();
    body.append('file', file);
    return requestJson<ExtractionResultV1>(`/api/v1/inquiries/${inquiryId}/files`, {
      method: 'POST',
      body,
    });
  },

  getInquiry(inquiryId) {
    return requestJson<InquiryV1>(`/api/v1/inquiries/${inquiryId}`);
  },

  getLines(inquiryId) {
    return requestJson<ExtractedInquiryLineV1[]>(`/api/v1/inquiries/${inquiryId}/lines`);
  },

  updateLine(lineId, update) {
    return requestJson<ExtractedInquiryLineV1>(`/api/v1/inquiry-lines/${lineId}`, {
      method: 'PATCH',
      body: JSON.stringify(update),
    });
  },

  validateLine(lineId) {
    return requestJson<ExtractedInquiryLineV1>(`/api/v1/inquiry-lines/${lineId}/validate`, {
      method: 'POST',
    });
  },
};
