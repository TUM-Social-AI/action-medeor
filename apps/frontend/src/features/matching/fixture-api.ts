import { startMatching, updateMatching } from '../../api/client';
import type { ErpMatch, MatchingResponse } from '../../api/types';
import type {
  MatchCandidateView,
  MatchingScreenView,
  MatchingWorkflowApi,
} from './models';

function toFixtureCandidate(match: ErpMatch, rank: number): MatchCandidateView {
  return {
    id: match.id,
    itemNumber: match.sku,
    name: match.name,
    manufacturer: match.manufacturer || undefined,
    rank,
    reviewStatus: 'unknown',
    availabilityStatus: match.lowStock ? 'on_hand_partial' : 'on_hand_sufficient',
    availabilityDetail: `${match.stock.toLocaleString()} ${match.unit}`,
    retrievalMethods: ['fixture'],
    constraintMessages: [],
    warnings: match.lowStock ? ['Fixture marks this product as low stock.'] : [],
    packaging: {
      status: 'unknown',
      options: [],
      warnings: [],
    },
  };
}

export function toFixtureMatchingView(response: MatchingResponse): MatchingScreenView {
  return {
    requestId: response.requestId,
    requestedLines: response.requestedItems.map(item => ({
      id: String(item.id),
      name: item.name,
      quantity: item.quantity,
      unit: item.unit,
      priority: item.priority,
    })),
    candidatesByLine: Object.fromEntries(
      Object.entries(response.matches).map(([lineId, matches]) => [
        lineId,
        matches.map((match, index) => toFixtureCandidate(match, index + 1)),
      ]),
    ),
    selectedCandidateIdsByLine: response.selectedMatches,
    errorsByLine: {},
  };
}

// Explicit adapter for the fixture-backed workflow currently provided by the UI branch.
// Replace this dependency with a real orchestrator after extraction and matching are available
// together; React components do not need to know which implementation is active.
export const fixtureMatchingWorkflowApi: MatchingWorkflowApi = {
  async start(requestId) {
    return toFixtureMatchingView(await startMatching(requestId));
  },

  async selectCandidate(requestId, lineId, candidateId) {
    const numericLineId = Number(lineId);
    if (!Number.isInteger(numericLineId)) {
      throw new Error(`Fixture matching requires a numeric line ID, received ${lineId}`);
    }
    await updateMatching(requestId, numericLineId, candidateId);
    return `fixture:${lineId}:${candidateId}`;
  },
};
