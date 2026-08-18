import type { InquiryLineV1, SourceReferenceV1 } from '../matching/contracts';

export type ExtractionStatus = 'queued' | 'processing' | 'completed' | 'failed';
export type LineValidationStatus = 'pending' | 'validated' | 'rejected';

export type ExtractedInquiryLineV1 = {
  line_id: string;
  extraction_id: string;
  position: number;
  raw_values: Record<string, unknown>;
  normalized: InquiryLineV1;
  validation_status: LineValidationStatus;
  validated_by?: string | null;
  validated_at?: string | null;
  extraction_confidence?: number | null;
  extraction_warnings: string[];
};

export type ExtractionResultV1 = {
  extraction_id: string;
  inquiry_id: string;
  status: ExtractionStatus;
  source: SourceReferenceV1;
  lines: ExtractedInquiryLineV1[];
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
};

export type InquiryV1 = {
  inquiry_id: string;
  partner_id?: string | null;
  destination_country?: string | null;
  latest_extraction?: ExtractionResultV1 | null;
  created_at: string;
  updated_at: string;
};

export type CreateInquiryRequest = {
  partner_id?: string | null;
  destination_country?: string | null;
};

export type InquiryLineUpdate = Partial<
  Pick<
    InquiryLineV1,
    | 'domain'
    | 'raw_description'
    | 'translated_description'
    | 'requested_item_number'
    | 'quantity'
    | 'package_request'
    | 'attributes'
    | 'urgency'
    | 'desired_shelf_life'
    | 'special_instructions'
  >
>;
