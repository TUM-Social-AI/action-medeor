import type { ExtractedInquiryLineV1 } from '../../api/extraction/contracts';

export type WorkflowState = {
  inquiryId?: string;
  extractionId?: string;
  lines: ExtractedInquiryLineV1[];
  matchRunIdsByLine: Record<string, string>;
  selectedCandidateIdsByLine: Record<string, string>;
  decisionIdsByLine: Record<string, string>;
};

export const emptyWorkflowState: WorkflowState = {
  lines: [],
  matchRunIdsByLine: {},
  selectedCandidateIdsByLine: {},
  decisionIdsByLine: {},
};
