import type { ExtractionApi } from '../../api/extraction';
import type { ExtractedInquiryLineV1 } from '../../api/extraction/contracts';
import type { MatchingApi } from '../../api/matching';
import type { MatchRunResponseV1 } from '../../api/matching/contracts';
import { toMatchCandidateView } from './mapper';
import type {
  MatchingScreenView,
  MatchingWorkflowApi,
  RequestedLineView,
} from './models';

type RealMatchingWorkflowOptions = {
  matchingApi: MatchingApi;
  extractionApi: ExtractionApi;
  actor?: string;
};

export function createRealMatchingWorkflowApi({
  matchingApi,
  extractionApi,
  actor,
}: RealMatchingWorkflowOptions): MatchingWorkflowApi {
  const runsByLine = new Map<string, MatchRunResponseV1>();

  return {
    async start(inquiryId) {
      const lines = await extractionApi.getLines(inquiryId);
      const validatedLines = lines.filter(line => line.validation_status === 'validated');

      if (validatedLines.length === 0) {
        throw new Error('Validate at least one extracted line before starting matching.');
      }

      const settledRuns = await Promise.allSettled(
        validatedLines.map(async line => {
          assertLineIdentity(inquiryId, line);
          const run = await matchingApi.createRun({
            contract_version: '1',
            inquiry_line: line.normalized,
          });
          runsByLine.set(line.line_id, run);
          return { line, run };
        }),
      );

      const candidatesByLine: MatchingScreenView['candidatesByLine'] = {};
      const errorsByLine: MatchingScreenView['errorsByLine'] = {};

      settledRuns.forEach((result, index) => {
        const line = validatedLines[index];
        if (result.status === 'fulfilled') {
          candidatesByLine[line.line_id] = result.value.run.candidates.map(toMatchCandidateView);
        } else {
          candidatesByLine[line.line_id] = [];
          errorsByLine[line.line_id] = errorMessage(result.reason);
        }
      });

      if (settledRuns.every(result => result.status === 'rejected')) {
        throw new Error('Matching failed for every validated inquiry line.');
      }

      return {
        requestId: inquiryId,
        requestedLines: validatedLines.map(toRequestedLineView),
        candidatesByLine,
        selectedCandidateIdsByLine: {},
        errorsByLine,
      };
    },

    async selectCandidate(_inquiryId, lineId, candidateId, overrideReason) {
      const run = runsByLine.get(lineId);
      if (!run) {
        throw new Error(`No matching run is available for inquiry line ${lineId}.`);
      }

      const candidate = run.candidates.find(item => item.candidate_id === candidateId);
      if (!candidate) {
        throw new Error('The selected candidate is not part of this matching run.');
      }

      const isFirstSuggestion = candidate.rank === 1;
      if (!isFirstSuggestion && !overrideReason?.trim()) {
        throw new Error('Please provide a reason when selecting an alternative candidate.');
      }

      const decision = await matchingApi.createDecision({
        contract_version: '1',
        match_run_id: run.match_run_id,
        inquiry_line_id: lineId,
        decision_type: isFirstSuggestion ? 'accept_suggestion' : 'select_alternative',
        candidate_id: candidate.candidate_id,
        selected_item_number: candidate.item_number,
        override_reason: isFirstSuggestion ? null : overrideReason?.trim(),
        actor,
      });
      return decision.decision_id;
    },
  };
}

function toRequestedLineView(line: ExtractedInquiryLineV1): RequestedLineView {
  return {
    id: line.line_id,
    name: line.normalized.translated_description ?? line.normalized.raw_description,
    quantity: numericQuantity(line.normalized.quantity.value),
    unit: line.normalized.quantity.unit ?? undefined,
    priority: priority(line.normalized.urgency),
  };
}

function numericQuantity(value: string | number | null | undefined): number | null {
  if (value == null) return null;
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function priority(value: string | null | undefined): RequestedLineView['priority'] {
  if (value === 'critical' || value === 'high' || value === 'medium' || value === 'low') {
    return value;
  }
  return undefined;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Matching failed for this inquiry line.';
}

function assertLineIdentity(inquiryId: string, line: ExtractedInquiryLineV1): void {
  if (line.normalized.inquiry_id !== inquiryId) {
    throw new Error(`Inquiry line ${line.line_id} belongs to a different inquiry.`);
  }
  if (line.normalized.line_id !== line.line_id) {
    throw new Error(`Extraction and matching line IDs differ for ${line.line_id}.`);
  }
}
