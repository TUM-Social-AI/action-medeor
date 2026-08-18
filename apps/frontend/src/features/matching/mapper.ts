import type {
  ExtractedInquiryLineV1,
  InquiryLineUpdate,
} from '../../api/extraction/contracts';
import type {
  InquiryLineV1,
  MatchCandidateV1,
  MatchRunResponseV1,
} from '../../api/matching/contracts';
import type { MatchCandidateView, MatchRunView } from './models';

export function toMatchCandidateView(candidate: MatchCandidateV1): MatchCandidateView {
  return {
    id: candidate.candidate_id,
    itemNumber: candidate.item_number,
    name: candidate.descriptions[0] ?? candidate.item_number,
    manufacturer: candidate.manufacturer ?? undefined,
    rank: candidate.rank,
    reviewStatus: candidate.review_status,
    availabilityStatus: candidate.availability_status,
    retrievalMethods: [...new Set(candidate.retrieval_evidence.map(item => item.retriever))],
    constraintMessages: candidate.constraints
      .filter(constraint => constraint.outcome !== 'pass')
      .map(constraint => constraint.message),
    warnings: [...new Set([...candidate.warnings, ...candidate.packaging.warnings])],
    packaging: candidate.packaging,
  };
}

export function toMatchRunView(run: MatchRunResponseV1): MatchRunView {
  return {
    id: run.match_run_id,
    inquiryId: run.inquiry_id,
    inquiryLineId: run.inquiry_line_id,
    status: run.status,
    candidates: run.candidates.map(toMatchCandidateView),
    validationWarnings: run.validation.warnings,
    error: run.error ?? undefined,
  };
}

export function applyInquiryLineUpdate(
  line: ExtractedInquiryLineV1,
  update: InquiryLineUpdate,
): InquiryLineV1 {
  return { ...line.normalized, ...update };
}
