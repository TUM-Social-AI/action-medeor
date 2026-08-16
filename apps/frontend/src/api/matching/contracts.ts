export type ProductDomain = 'medicine' | 'equipment';
export type SourceType =
  | 'excel'
  | 'outlook_message'
  | 'outlook_attachment'
  | 'sharepoint'
  | 'erp'
  | 'supplier'
  | 'other';
export type ValidationStatus =
  | 'valid'
  | 'valid_with_warnings'
  | 'review_required'
  | 'invalid';
export type RuleOutcome = 'pass' | 'exclude' | 'review' | 'warning' | 'unknown';
export type AvailabilityStatus =
  | 'on_hand_sufficient'
  | 'on_hand_partial'
  | 'procurement_indicated'
  | 'unknown'
  | 'not_allowed';
export type MatchRunStatus = 'running' | 'completed' | 'failed';
export type DecisionType =
  | 'accept_suggestion'
  | 'select_alternative'
  | 'manual_match'
  | 'no_match'
  | 'procurement_required';

export type SourceReferenceV1 = {
  contract_version: '1';
  source_type: SourceType;
  document_id: string;
  external_id?: string | null;
  uri?: string | null;
  checksum?: string | null;
  captured_at: string;
  sheet?: string | null;
  row?: number | null;
  locator: Record<string, unknown>;
};

export type AttributeValue = {
  value: string | number | boolean;
  unit?: string | null;
  raw_value?: string | null;
  confidence?: number | null;
};

export type QuantityValue = {
  value?: string | number | null;
  unit?: string | null;
  raw_expression?: string | null;
};

export type ProductPackage = {
  units_per_package?: string | number | null;
  unit?: string | null;
  package_label?: string | null;
};

export type InquiryLineV1 = {
  contract_version: '1';
  inquiry_id: string;
  line_id: string;
  domain: ProductDomain;
  raw_description: string;
  translated_description?: string | null;
  requested_item_number?: string | null;
  quantity: QuantityValue;
  package_request?: ProductPackage | null;
  attributes: Record<string, AttributeValue>;
  partner_id?: string | null;
  destination_country?: string | null;
  urgency?: string | null;
  desired_shelf_life?: string | null;
  special_instructions: string[];
  parsing_warnings: string[];
  source: SourceReferenceV1;
};

export type MatchRequestV1 = {
  contract_version: '1';
  inquiry_line: InquiryLineV1;
  catalog_snapshot_id?: string | null;
  top_k?: number;
  retrieval_limit?: number;
  query_embedding?: number[] | null;
  embedding_model_id?: string | null;
};

export type ValidationReport = {
  status: ValidationStatus;
  warnings: string[];
  errors: string[];
};

export type ConstraintResult = {
  code: string;
  outcome: RuleOutcome;
  message: string;
  attribute?: string | null;
  requested_value?: string | null;
  candidate_value?: string | null;
};

export type RetrievalEvidence = {
  retriever: string;
  rank: number;
  score?: number | null;
  details: Record<string, unknown>;
};

export type PackagingOption = {
  packages: number;
  total_units: string | number;
  difference: string | number;
  direction: string;
};

export type PackagingResult = {
  status: string;
  options: PackagingOption[];
  recommended_option?: PackagingOption | null;
  warnings: string[];
};

export type MatchCandidateV1 = {
  candidate_id: string;
  item_number: string;
  candidate_type: 'catalog' | 'historical_offer' | 'procurement';
  rank: number;
  descriptions: string[];
  manufacturer?: string | null;
  review_status: RuleOutcome;
  availability_status: AvailabilityStatus;
  retrieval_evidence: RetrievalEvidence[];
  score_components: Record<string, number>;
  constraints: ConstraintResult[];
  packaging: PackagingResult;
  warnings: string[];
  provenance: SourceReferenceV1[];
};

export type MatchRunResponseV1 = {
  contract_version: '1';
  match_run_id: string;
  status: MatchRunStatus;
  inquiry_id: string;
  inquiry_line_id: string;
  algorithm_version: string;
  policy_version: string;
  embedding_model_id?: string | null;
  validation: ValidationReport;
  candidates: MatchCandidateV1[];
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
};

export type MatchDecisionRequestV1 = {
  contract_version: '1';
  match_run_id: string;
  inquiry_line_id: string;
  decision_type: DecisionType;
  candidate_id?: string | null;
  selected_item_number?: string | null;
  offered_quantity?: string | number | null;
  override_reason?: string | null;
  note?: string | null;
  actor?: string | null;
};

export type MatchDecisionResponseV1 = {
  decision_id: string;
  match_run_id: string;
  decision_type: DecisionType;
  created_at: string;
};
