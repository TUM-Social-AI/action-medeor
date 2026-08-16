import { requestJson } from '../http';
import type {
  MatchDecisionRequestV1,
  MatchDecisionResponseV1,
  MatchRequestV1,
  MatchRunResponseV1,
} from './contracts';

export interface MatchingApi {
  createRun(request: MatchRequestV1): Promise<MatchRunResponseV1>;
  getRun(matchRunId: string): Promise<MatchRunResponseV1>;
  createDecision(decision: MatchDecisionRequestV1): Promise<MatchDecisionResponseV1>;
}

export const httpMatchingApi: MatchingApi = {
  createRun(request) {
    return requestJson<MatchRunResponseV1>('/api/v1/match-runs', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  getRun(matchRunId) {
    return requestJson<MatchRunResponseV1>(`/api/v1/match-runs/${matchRunId}`);
  },

  createDecision(decision) {
    return requestJson<MatchDecisionResponseV1>('/api/v1/match-decisions', {
      method: 'POST',
      body: JSON.stringify(decision),
    });
  },
};
