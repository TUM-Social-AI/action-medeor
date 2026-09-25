import { useEffect, useState } from 'react';
import { ArrowRight, RefreshCw } from 'lucide-react';
import {
  decideRequestMatch,
  getRequestMatching,
  startRequestMatching,
  type SavedMatching,
} from '../api/workflow';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type Props = { requestId: string; onContinue: () => void };
type PendingChoice = { itemId: number; candidateId: string } | null;

export function SmartMatchingScreen({ requestId, onContinue }: Props) {
  const [data, setData] = useState<SavedMatching | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingChoice, setPendingChoice] = useState<PendingChoice>(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = () => getRequestMatching(requestId)
      .then(value => { if (active) { setData(value); setError(null); } })
      .catch(caught => { if (active) setError(String(caught)); });
    void refresh();
    const timer = window.setInterval(() => {
      if (active) void refresh();
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [requestId]);

  const choose = async (itemId: number, candidateId?: string, overrideReason?: string) => {
    setSaving(true);
    try {
      setData(await decideRequestMatch(requestId, itemId, {
        candidateId,
        noMatch: !candidateId,
        overrideReason,
      }));
      setPendingChoice(null);
      setReason('');
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the decision');
    } finally {
      setSaving(false);
    }
  };

  const retry = async () => {
    try {
      setData(await startRequestMatching(requestId));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not retry matching');
    }
  };

  if (!data) return <div className="p-6"><LoadingPanel label="Loading saved matching results" /></div>;

  return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-5">
        <WorkflowStepper currentStep="matching" />
      </div>
      <h1 className="text-gray-900 mb-1">Smart Matching</h1>
      <p className="text-sm text-gray-500 mb-4">
        {data.completed} of {data.total} items matched. Results and selections are saved to this request.
      </p>
      {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
      {data.status === 'matching_failed' && (
        <button onClick={() => void retry()} className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-100 text-amber-800 rounded-lg">
          <RefreshCw size={14} /> Retry failed items
        </button>
      )}
      <div className="space-y-5">
        {data.lines.map(line => (
          <section key={line.itemId} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex justify-between gap-4 mb-3">
              <div>
                <h2 className="font-semibold text-gray-900">{line.name}</h2>
                <p className="text-xs text-gray-500">{line.domain} · {line.quantity ?? 'Unknown quantity'} {line.unit}</p>
              </div>
              <span className="text-xs text-gray-500">{line.status}</span>
            </div>
            {line.error && <p className="text-sm text-red-700 mb-3">{line.error}</p>}
            {(line.status === 'pending' || line.status === 'running') && <LoadingPanel label={line.status === 'running' ? 'Matching this item' : 'Waiting for matching worker'} />}
            {line.status === 'completed' && (
              <>
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                  {line.candidates.map(candidate => (
                    <button
                      key={candidate.candidate_id}
                      disabled={saving}
                      onClick={() => {
                        if (candidate.rank === 1) void choose(line.itemId, candidate.candidate_id);
                        else { setPendingChoice({ itemId: line.itemId, candidateId: candidate.candidate_id }); setReason(''); }
                      }}
                      className={`text-left rounded-lg border-2 p-4 hover:border-[#1B4E8A] ${
                        line.selectedCandidateId === candidate.candidate_id ? 'border-[#1B4E8A] bg-blue-50' : 'border-gray-200'
                      }`}
                    >
                      <div className="text-xs text-gray-500 mb-1">#{candidate.rank} · {candidate.item_number}</div>
                      <div className="font-semibold text-sm text-gray-900 mb-2">{candidate.descriptions[0]}</div>
                      <div className="text-xs text-gray-600">Availability: {candidate.availability_status.replace(/_/g, ' ')}</div>
                      <div className="text-xs text-blue-700 mt-2 space-y-0.5">
                        {candidate.retrieval_evidence.map((evidence, index) => (
                          <div key={`${evidence.retriever}-${index}`}>
                            {evidence.retriever} rank {evidence.rank}
                            {typeof evidence.score === 'number' ? ` · retrieval score ${evidence.score.toFixed(3)}` : ''}
                            {typeof evidence.details.model_id === 'string' ? ` · ${evidence.details.model_id}` : ''}
                          </div>
                        ))}
                      </div>
                      {candidate.constraints.map(value => (
                        <p key={value.code} className={`text-xs mt-1 ${value.outcome === 'pass' ? 'text-gray-500' : 'text-amber-700'}`}>{value.outcome}: {value.message}</p>
                      ))}
                      {candidate.warnings.map(warning => (
                        <p key={warning} className="text-xs text-amber-700 mt-1">{warning}</p>
                      ))}
                    </button>
                  ))}
                </div>
                <button
                  disabled={saving}
                  onClick={() => void choose(line.itemId)}
                  className={`mt-3 text-sm px-3 py-2 rounded-lg border ${line.decisionType === 'no_match' ? 'border-[#1B4E8A] bg-blue-50' : 'border-gray-300'}`}
                >
                  No match
                </button>
                {line.decisionType && <span className="ml-3 text-xs text-green-700">Decision saved</span>}
              </>
            )}
          </section>
        ))}
      </div>
      <div className="mt-8 flex justify-end">
        <button
          disabled={data.status !== 'complete'}
          onClick={onContinue}
          className="flex items-center gap-2 px-6 py-3 rounded-lg bg-[#1B4E8A] text-white disabled:bg-gray-300"
        >
          Continue to Summary <ArrowRight size={16} />
        </button>
      </div>
      {pendingChoice && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-5">
          <div className="bg-white rounded-xl p-6 w-full max-w-md">
            <h2 className="font-semibold mb-2">Why choose this alternative?</h2>
            <textarea
              value={reason}
              onChange={event => setReason(event.target.value)}
              className="w-full border rounded-lg p-3 text-sm"
              rows={3}
              autoFocus
            />
            <div className="flex justify-end gap-3 mt-4">
              <button onClick={() => setPendingChoice(null)}>Cancel</button>
              <button
                disabled={!reason.trim() || saving}
                onClick={() => void choose(pendingChoice.itemId, pendingChoice.candidateId, reason.trim())}
                className="px-4 py-2 rounded-lg bg-[#1B4E8A] text-white disabled:bg-gray-300"
              >Save decision</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
