import type {
  AvailabilityStatus,
  PackagingResult,
  RuleOutcome,
} from '../../api/matching/contracts';

export type MatchCandidateView = {
  id: string;
  itemNumber: string;
  name: string;
  manufacturer?: string;
  rank: number;
  reviewStatus: RuleOutcome;
  availabilityStatus: AvailabilityStatus;
  retrievalMethods: string[];
  constraintMessages: string[];
  warnings: string[];
  packaging: PackagingResult;
  availabilityDetail?: string;
};

export type MatchRunView = {
  id: string;
  inquiryId: string;
  inquiryLineId: string;
  status: 'running' | 'completed' | 'failed';
  candidates: MatchCandidateView[];
  validationWarnings: string[];
  error?: string;
};

export type RequestedLineView = {
  id: string;
  name: string;
  quantity: number | null;
  unit?: string;
  priority?: 'critical' | 'high' | 'medium' | 'low';
};

export type MatchingScreenView = {
  requestId: string;
  requestedLines: RequestedLineView[];
  candidatesByLine: Record<string, MatchCandidateView[]>;
  selectedCandidateIdsByLine: Record<string, string>;
  errorsByLine: Record<string, string>;
};

export interface MatchingWorkflowApi {
  start(requestId: string): Promise<MatchingScreenView>;
  selectCandidate(
    requestId: string,
    lineId: string,
    candidateId: string,
    overrideReason?: string,
  ): Promise<string>;
}
