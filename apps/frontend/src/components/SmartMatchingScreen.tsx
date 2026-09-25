import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Ban, ChevronDown, ChevronUp, Info, MapPin, RefreshCw, X } from 'lucide-react';
import type { MatchCandidateV1 } from '../api/matching/contracts';
import {
  autoSelectRequestMatches,
  decideRequestMatch,
  getRequestMatching,
  startRequestMatching,
  type SavedMatching,
  type SavedMatchLine,
} from '../api/workflow';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { formatRankingScore } from '../features/matching/format-ranking-score';
import { WorkflowStepper } from './WorkflowStepper';

type Props = { requestId: string; onContinue: () => Promise<void> };
type CandidateDetails = { line: SavedMatchLine; candidate: MatchCandidateV1 } | null;
const VISIBLE_COUNT = 3;

function selectionLabel(line: SavedMatchLine) {
  if (line.decisionType === 'no_match') return 'Marked unmatched';
  if (line.selectedCandidateId) return 'Article selected';
  if (line.status === 'completed') return 'Awaiting your selection';
  return line.status;
}

function checkLabel(outcome: string) {
  return ({ pass: 'Confirmed', review: 'Needs review', warning: 'Warning', unknown: 'Unconfirmed', exclude: 'Excluded' } as Record<string, string>)[outcome] ?? outcome;
}

function CandidateCard({
  candidate, selected, disabled, onSelect, onInfo,
}: {
  candidate: MatchCandidateV1;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
  onInfo: () => void;
}) {
  const availability = candidate.availability_status.replace(/_/g, ' ');
  const firstWarning = candidate.constraints.find(value => value.outcome !== 'pass')?.message ?? candidate.warnings[0];
  const rankingScore = candidate.score_components.ranking_score;
  return <div className={'relative border-2 rounded-xl transition-colors ' + (selected ? 'border-[#1B4E8A] bg-blue-50/40' : 'border-gray-200 hover:border-gray-300')}>
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-label={'Select ' + (candidate.descriptions[0] || candidate.item_number)}
      aria-pressed={selected}
      className="w-full h-full text-left p-4 pr-11 disabled:cursor-wait"
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className={'w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ' + (selected ? 'border-[#1B4E8A] bg-[#1B4E8A]' : 'border-gray-300')}>
            {selected && <span className="w-2 h-2 rounded-full bg-white" />}
          </span>
          <span className="text-2xl leading-none text-gray-900 font-extrabold">{typeof rankingScore === 'number' ? formatRankingScore(rankingScore) : '—'}</span>
          <span className="text-xs text-gray-500 leading-tight">/100<br />Ranking score</span>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="text-xs text-gray-400">#{candidate.rank}</span>
          {candidate.rank === 1 && <span className="px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded text-xs font-bold">TOP SUGGESTION</span>}
          {selected && <span className="px-1.5 py-0.5 bg-[#1B4E8A] text-white rounded text-xs font-bold">SELECTED</span>}
        </div>
      </div>
      <div className="text-sm text-gray-900 mb-3 leading-snug font-bold">{candidate.descriptions[0] || candidate.item_number}</div>
      <div className="space-y-1 text-xs">
        <div><span className="text-gray-400 font-semibold inline-block w-14">SKU</span><span className="text-gray-700 font-mono">{candidate.item_number}</span></div>
        {candidate.manufacturer && <div><span className="text-gray-400 font-semibold inline-block w-14">MFR</span><span className="text-gray-700">{candidate.manufacturer}</span></div>}
        <div><span className="text-gray-400 font-semibold inline-block w-14">AVAIL.</span><span className={candidate.availability_status === 'on_hand_sufficient' ? 'text-green-700 font-semibold' : 'text-gray-600'}>{availability}</span></div>
      </div>
      {firstWarning && <p className="mt-3 text-xs text-amber-700 leading-snug line-clamp-2">{firstWarning}</p>}
    </button>
    <button type="button" onClick={onInfo} aria-label={'Details for ' + (candidate.descriptions[0] || candidate.item_number)} title="Match details" className="absolute right-3 bottom-3 p-1.5 rounded-full text-[#1B4E8A] hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]">
      <Info size={17} />
    </button>
  </div>;
}

export function SmartMatchingScreen({ requestId, onContinue }: Props) {
  const [data, setData] = useState<SavedMatching | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<CandidateDetails>(null);
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  const [savingItems, setSavingItems] = useState<Set<number>>(new Set());
  const savingItemsRef = useRef<Set<number>>(new Set());
  const decisionVersion = useRef(0);
  const [finalizing, setFinalizing] = useState(false);
  const [showUndecided, setShowUndecided] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      const version = decisionVersion.current;
      return getRequestMatching(requestId)
        .then(value => {
          if (active && savingItemsRef.current.size === 0 && version === decisionVersion.current) {
            setData(value);
            setError(null);
          }
        })
        .catch(caught => { if (active) setError(String(caught)); });
    };
    const initialVersion = decisionVersion.current;
    void autoSelectRequestMatches(requestId)
      .then(value => {
        if (active && savingItemsRef.current.size === 0 && initialVersion === decisionVersion.current) {
          setData(value);
          setError(null);
        }
      })
      .catch(() => { if (active) void refresh(); });
    const timer = window.setInterval(() => { if (active) void refresh(); }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [requestId]);

  const choose = async (itemId: number, candidateId?: string) => {
    if (savingItemsRef.current.has(itemId)) return;
    decisionVersion.current += 1;
    savingItemsRef.current.add(itemId);
    setSavingItems(new Set(savingItemsRef.current));
    try {
      const updated = await decideRequestMatch(requestId, itemId, {
        candidateId, noMatch: !candidateId,
      });
      // Another line can be decided at the same time. Apply only this line from
      // the response so an older response cannot undo the other local choice.
      setData(previous => previous ? {
        ...updated,
        lines: previous.lines.map(line =>
          line.itemId === itemId
            ? updated.lines.find(updatedLine => updatedLine.itemId === itemId) ?? line
            : line,
        ),
      } : updated);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the decision');
    } finally {
      savingItemsRef.current.delete(itemId);
      decisionVersion.current += 1;
      setSavingItems(new Set(savingItemsRef.current));
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

  const toggleExpand = (itemId: number) => setExpandedItems(previous => {
    const next = new Set(previous);
    if (next.has(itemId)) next.delete(itemId);
    else next.add(itemId);
    return next;
  });

  const undecided = data?.lines.filter(line => !line.decisionType) ?? [];
  const canFinalize = data?.total && undecided.length === 0 && data.lines.every(line => line.status === 'completed');
  const continueOrReview = async () => {
    if (!canFinalize) { setShowUndecided(true); return; }
    setFinalizing(true);
    try {
      await onContinue();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not finalize request');
    } finally {
      setFinalizing(false);
    }
  };
  const jumpTo = (itemId: number) => {
    setShowUndecided(false);
    document.getElementById('match-item-' + itemId)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  if (!data) return <div className="p-6"><LoadingPanel label="Loading saved matching results" /></div>;

  return <div className="p-6 pb-32">
    <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-5"><WorkflowStepper currentStep="matching" /></div>
    <div className="mb-5">
      <h1>Smart Matching</h1>
      <p className="text-gray-500 text-sm mt-0.5">
        Search finished for {data.completed} of {data.total} items. Review suggestions and choose an article or mark each item unmatched. The ranking score is calculated from the matching evidence before candidates are sorted. The best option scores 100; the others are scaled against it. Scores are only comparable within one item and are not confidence percentages. Your decisions are saved.
      </p>
    </div>
    {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
    {data.status === 'matching_failed' && <button onClick={() => void retry()} className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-100 text-amber-800 rounded-lg"><RefreshCw size={14} /> Retry failed items</button>}
    <div className="space-y-4">
      {data.lines.map(line => {
        const expanded = expandedItems.has(line.itemId);
        const visible = expanded ? line.candidates : line.candidates.slice(0, VISIBLE_COUNT);
        const selectedOutside = !expanded && line.candidates.slice(VISIBLE_COUNT).find(candidate => candidate.candidate_id === line.selectedCandidateId);
        return <section id={'match-item-' + line.itemId} key={line.itemId} className="bg-white rounded-xl border-2 border-gray-200 overflow-hidden scroll-mt-6">
          <div className="px-5 py-3.5 bg-gray-50 border-b border-gray-200 flex items-center gap-3">
            <MapPin size={15} className="text-gray-400 flex-shrink-0" />
            <div className="flex-1 flex items-center gap-3 flex-wrap">
              <span className="text-sm text-gray-900 font-bold">{line.name}</span>
              <span className="text-sm text-gray-500">Qty: {line.quantity?.toLocaleString() ?? 'Not specified'} {line.unit}</span>
              <span className="text-xs text-gray-500 capitalize">{line.domain}</span>
            </div>
            <span className={'flex-shrink-0 px-2.5 py-1 rounded-full text-xs font-semibold ' + (line.decisionType ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700')}>{selectionLabel(line)}</span>
          </div>
          <div className="p-5">
            {line.error && <div className="mb-3"><ErrorPanel message={line.error} /></div>}
            {(line.status === 'pending' || line.status === 'running') && <LoadingPanel label={line.status === 'running' ? 'Matching this item' : 'Waiting for matching worker'} />}
            {line.status === 'completed' && <>
              {line.candidates.length === 0 && <p className="text-sm text-gray-500">No candidates were found for this item.</p>}
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {visible.map(candidate => <CandidateCard
                  key={candidate.candidate_id}
                  candidate={candidate}
                  selected={line.selectedCandidateId === candidate.candidate_id}
                  disabled={savingItems.has(line.itemId)}
                  onSelect={() => void choose(line.itemId, candidate.candidate_id)}
                  onInfo={() => setDetails({ line, candidate })}
                />)}
              </div>
              {selectedOutside && <div className="mt-4">
                <div className="flex items-center gap-2 mb-2.5"><div className="flex-1 h-px bg-gray-200" /><span className="text-xs text-gray-400">Your current selection</span><div className="flex-1 h-px bg-gray-200" /></div>
                <div className="max-w-md"><CandidateCard candidate={selectedOutside} selected disabled={savingItems.has(line.itemId)} onSelect={() => void choose(line.itemId, selectedOutside.candidate_id)} onInfo={() => setDetails({ line, candidate: selectedOutside })} /></div>
              </div>}
              {line.candidates.length > VISIBLE_COUNT && <button onClick={() => toggleExpand(line.itemId)} className="mt-3 flex items-center gap-1 text-sm text-[#1B4E8A] hover:underline">
                {expanded ? <><ChevronUp size={14} /> Show fewer options</> : <><ChevronDown size={14} /> See {line.candidates.length - VISIBLE_COUNT} more options</>}
              </button>}
              <div className="mt-4 pt-3 border-t border-gray-100 flex items-center gap-3">
                <button type="button" disabled={savingItems.has(line.itemId)} aria-pressed={line.decisionType === 'no_match'} onClick={() => void choose(line.itemId)} className={'inline-flex items-center gap-2 rounded-lg border-2 px-4 py-2.5 text-sm font-semibold shadow-sm transition-colors disabled:opacity-50 ' + (line.decisionType === 'no_match' ? 'border-[#1B4E8A] bg-[#1B4E8A] text-white' : 'border-[#1B4E8A] bg-white text-[#1B4E8A] hover:bg-blue-50')}><Ban size={16} /> Mark this item as unmatched</button>
                {line.decisionType && <span className="text-xs text-green-700">Decision saved</span>}
              </div>
            </>}
          </div>
        </section>;
      })}
    </div>
    <div className="fixed bottom-0 left-56 right-0 z-20 bg-white border-t border-gray-200 shadow-lg px-6 py-3">
      {showUndecided && undecided.length > 0 && <div className="absolute bottom-full right-6 w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-xl max-h-72 overflow-y-auto p-2 mb-2">
        <div className="px-3 py-2 text-sm font-semibold text-gray-900">Items still needing a decision</div>
        {undecided.map(line => <button key={line.itemId} onClick={() => jumpTo(line.itemId)} className="block w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-blue-50 text-[#1B4E8A]">
          <span className="block truncate">{line.name}</span><span className="text-xs text-gray-500">{line.status === 'completed' ? 'Choose an article or mark unmatched' : line.status}</span>
        </button>)}
      </div>}
      <div className="flex items-center justify-between gap-4 max-w-6xl mx-auto">
        <button onClick={() => setShowUndecided(value => !value)} className="text-sm text-[#1B4E8A] hover:underline text-left" aria-expanded={showUndecided}>
          {undecided.length ? undecided.length + ' of ' + data.total + ' items need a decision · View items' : 'All ' + data.total + ' items have a decision'}
        </button>
        <button disabled={savingItems.size > 0 || finalizing} onClick={() => void continueOrReview()} className="flex items-center gap-2 px-6 py-3 rounded-xl bg-[#1B4E8A] text-white disabled:bg-gray-300 font-bold whitespace-nowrap">
          {finalizing ? 'Saving final state…' : 'Continue to Summary'} <ArrowRight size={16} />
        </button>
      </div>
    </div>

    {details && <div className="fixed inset-0 z-30 bg-black/40 flex items-center justify-center p-5" onClick={() => setDetails(null)}>
      <div role="dialog" aria-modal="true" aria-label="Match details" className="bg-white rounded-xl p-6 w-full max-w-xl max-h-[85vh] overflow-y-auto shadow-xl" onClick={event => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 mb-4">
          <div><h2 className="font-semibold text-gray-900">Match details</h2><p className="text-sm text-gray-600">{details.candidate.descriptions[0]}</p></div>
          <button onClick={() => setDetails(null)} aria-label="Close match details" className="p-1 text-gray-500 hover:text-gray-900"><X size={18} /></button>
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm mb-5">
          <div><dt className="text-gray-500">Requested item</dt><dd className="font-medium">{details.line.name}</dd></div>
          <div><dt className="text-gray-500">Article number</dt><dd className="font-mono">{details.candidate.item_number}</dd></div>
          <div><dt className="text-gray-500">Availability</dt><dd>{details.candidate.availability_status.replace(/_/g, ' ')}</dd></div>
          <div><dt className="text-gray-500">Automated checks</dt><dd>{details.candidate.review_status === 'pass' ? 'No configured issue found' : details.candidate.review_status.replace(/_/g, ' ')}</dd></div>
          {details.candidate.manufacturer && <div><dt className="text-gray-500">Manufacturer</dt><dd>{details.candidate.manufacturer}</dd></div>}
          <div><dt className="text-gray-500">Packaging</dt><dd>{details.candidate.packaging.status.replace(/_/g, ' ')}</dd></div>
          <div><dt className="text-gray-500">Ranking score</dt><dd>{typeof details.candidate.score_components.ranking_score === 'number' ? formatRankingScore(details.candidate.score_components.ranking_score) : '—'}</dd></div>
          <div><dt className="text-gray-500">Exact reference</dt><dd>{details.candidate.score_components.exact_reference ? 'Yes' : 'No'}</dd></div>
          <div><dt className="text-gray-500">Attribute agreement</dt><dd>{typeof details.candidate.score_components.attribute_match_ratio === 'number' ? Math.round(details.candidate.score_components.attribute_match_ratio * 100) + '%' : 'No comparable attributes'}</dd></div>
          <div><dt className="text-gray-500">Fused retrieval</dt><dd>{details.candidate.score_components.rrf?.toFixed(4) ?? '—'}</dd></div>
        </dl>
        <p className="text-xs text-gray-500 mb-5">The ranking score is computed before sorting from the matcher’s priority rules: checks, exact references, attribute agreement, fused retrieval, availability, and article number. It preserves that priority order. The best evaluated candidate is 100. Scores are scaled across all evaluated candidates; the lowest may be outside the displayed top options. This relative scale is not a confidence percentage. Checks cover configured attributes only.</p>
        <p className="text-xs text-gray-500 mb-3">Name similarity: {typeof details.candidate.score_components.name_similarity === 'number' ? Math.round(details.candidate.score_components.name_similarity * 100) + '/100' : 'unavailable'}</p>
        <h3 className="text-sm font-semibold mb-2">Retrieval evidence</h3>
        {details.candidate.retrieval_evidence.length ? <ul className="space-y-1 mb-5 text-sm text-gray-700">{details.candidate.retrieval_evidence.map((evidence, index) => <li key={index} className="rounded-lg bg-gray-50 p-2">
          {evidence.retriever} rank {evidence.rank}{typeof evidence.score === 'number' ? ' · score ' + evidence.score.toFixed(3) : ''}
          {typeof evidence.details.model_id === 'string' ? ' · ' + evidence.details.model_id : ''}
        </li>)}</ul> : <p className="text-sm text-gray-500 mb-5">No retrieval evidence saved.</p>}
        {details.candidate.constraints.length > 0 && <><h3 className="text-sm font-semibold mb-2">Checks</h3><ul className="space-y-1 mb-5 text-sm">{details.candidate.constraints.map(value => <li key={value.code} className={value.outcome === 'pass' ? 'text-gray-600' : 'text-amber-700'}>{checkLabel(value.outcome)}: {value.message}</li>)}</ul></>}
        {details.candidate.warnings.length > 0 && <><h3 className="text-sm font-semibold mb-2">Warnings</h3><ul className="space-y-1 text-sm text-amber-700">{details.candidate.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></>}
      </div>
    </div>}

  </div>;
}
