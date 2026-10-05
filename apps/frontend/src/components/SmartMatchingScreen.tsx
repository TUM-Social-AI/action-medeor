import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowRight, Ban, CalendarX2, Check, ChevronDown, ChevronUp, Info, MapPin, RefreshCw, X } from 'lucide-react';
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
import { getCandidatePackSize } from '../features/matching/pack-size-display';
import { formatOfferPrice, getOfferStatus } from '../features/matching/offer-display';
import { useOfferDateRefresh } from '../features/matching/use-offer-date-refresh';
import { WorkflowStepper } from './WorkflowStepper';
import { SharePointOfferSource } from './SharePointOfferSource';
import { CandidateAvailability } from './CandidateAvailability';

type Props = { requestId: string; onContinue: () => Promise<void> };
type CandidateDetails = { line: SavedMatchLine; candidate: MatchCandidateV1 } | null;
const LARGE_SCREEN_QUERY = '(min-width: 1280px)';

function selectionLabel(line: SavedMatchLine) {
  if (line.decisionType === 'no_match') return 'Marked unmatched';
  if (line.selectedCandidateId) return line.candidates.find(candidate => candidate.candidate_id === line.selectedCandidateId)?.candidate_type === 'historical_offer' ? 'Offer selected' : 'Article selected';
  if (line.status === 'completed') return 'Awaiting your selection';
  return line.status;
}

function checkLabel(outcome: string) {
  return ({ pass: 'Confirmed', review: 'Needs review', warning: 'Warning', unknown: 'Unconfirmed', exclude: 'Excluded' } as Record<string, string>)[outcome] ?? outcome;
}

function OfferBadge({ candidate }: { candidate: MatchCandidateV1 }) {
  const status = getOfferStatus(candidate);
  if (!status.badge) return null;
  return <span className="inline-flex items-center gap-1 rounded bg-rose-100 px-1.5 py-0.5 text-[11px] font-bold text-rose-700">
    <CalendarX2 size={10} /> {status.badge}
  </span>;
}

function OfferValidity({ candidate }: { candidate: MatchCandidateV1 }) {
  const status = getOfferStatus(candidate);
  return <span className={status.warning ? 'font-semibold text-red-700' : 'text-gray-700'}>{status.label}</span>;
}

function OfferPriceAndValidity({ candidate }: { candidate: MatchCandidateV1 }) {
  const status = getOfferStatus(candidate);
  return <span>
    <span className={status.expired ? 'text-gray-400 line-through decoration-gray-300' : candidate.unit_price == null && candidate.price == null ? 'italic text-gray-500' : 'font-medium text-gray-700'}>{formatOfferPrice(candidate.price, candidate.currency, candidate.price_basis, candidate.unit_price, candidate.unit_price_unit)}</span>
    <span className="text-gray-400"> · </span>
    <OfferValidity candidate={candidate} />
  </span>;
}

function OfferFollowUp({ candidate }: { candidate: MatchCandidateV1 }) {
  if (!getOfferStatus(candidate).muted) return null;
  return <p className="mt-3 text-xs font-semibold text-rose-700">Contact the supplier to receive a new offer.</p>;
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
  const offer = candidate.candidate_type === 'historical_offer';
  const status = getOfferStatus(candidate);
  const muted = offer && status.muted;
  const name = candidate.descriptions[0] || candidate.item_number || 'Supplier offer';
  const firstWarning = offer ? undefined : candidate.constraints.find(value => value.outcome !== 'pass')?.message;
  const rankingScore = candidate.score_components.ranking_score;
  const packSize = getCandidatePackSize(candidate);
  return <div className={'relative flex h-full flex-col overflow-hidden rounded-xl border-2 transition-colors ' + (muted
    ? (selected ? 'border-[#1B4E8A] shadow-sm ' : 'border-dashed border-gray-300 hover:border-gray-400 ') + 'bg-[repeating-linear-gradient(135deg,#f9fafb_0_8px,#f3f4f6_8px_16px)]'
    : selected ? 'border-[#1B4E8A] bg-blue-50/40 shadow-sm'
    : offer ? 'border-violet-200 bg-violet-50/40 hover:border-violet-300 hover:shadow-sm'
      : 'border-gray-200 hover:border-gray-300 hover:shadow-sm')}>
    <button type="button" onClick={onSelect} disabled={disabled} aria-label={'Select ' + name} aria-pressed={selected}
      className="flex w-full flex-1 flex-col p-4 pr-11 text-left disabled:cursor-wait">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ' + (selected ? 'border-[#1B4E8A] bg-[#1B4E8A]' : 'border-gray-300 bg-white')}>
            {selected && <span className="h-2 w-2 rounded-full bg-white" />}
          </span>
          <span className={"text-2xl font-extrabold leading-none " + (muted ? "text-gray-400" : "text-gray-900")}>{typeof rankingScore === 'number' ? formatRankingScore(rankingScore) : '—'}</span>
          <span className="text-xs leading-tight text-gray-500">/100<br />Ranking score</span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {candidate.rank === 1 && !muted ? <span className="rounded bg-teal-100 px-1.5 py-0.5 text-[11px] font-bold text-teal-700">BEST FIT</span> : null}
          {offer && <OfferBadge candidate={candidate} />}
        </div>
      </div>
      <div title={name} className={"mb-2 h-[2.75em] shrink-0 line-clamp-2 break-words text-sm font-bold leading-snug " + (muted ? "text-gray-500" : "text-gray-900")}>{name}</div>
      {offer ? <div className="space-y-1.5 text-xs">
        <div className="flex gap-2"><span className="w-16 shrink-0 text-[11px] font-semibold text-gray-400">SUPPLIER</span><span className="font-medium text-gray-700">{candidate.supplier || 'Not specified'}</span></div>
        <div className="flex gap-2"><span className="w-16 shrink-0 text-[11px] font-semibold text-gray-400">{candidate.unit_price != null ? 'UNIT PRICE' : 'PRICE'}</span><OfferPriceAndValidity candidate={candidate} /></div>
      </div> : <div className="space-y-1.5 text-xs">
        <div className="flex gap-2"><span className="w-16 shrink-0 text-[11px] font-semibold text-gray-400">ERP ID</span><span className="text-gray-700">{candidate.item_number || 'Not specified'}</span></div>
        <div className="flex gap-2"><span className="w-16 shrink-0 text-[11px] font-semibold text-gray-400">PACK SIZE</span><span className={packSize ? 'text-gray-700' : 'text-gray-400'} title={candidate.package?.package_label || candidate.packaging.basis || undefined}>{packSize || 'Not recorded'}</span></div>
        <div className="flex gap-2"><span className="w-16 shrink-0 text-[11px] font-semibold text-gray-400">AVAIL.</span><CandidateAvailability candidate={candidate} /></div>
      </div>}
      {firstWarning && <p className="mt-3 line-clamp-2 text-xs leading-snug text-amber-700">{firstWarning}</p>}
    </button>
    {offer ? <SharePointOfferSource provenance={candidate.provenance} candidateType={candidate.candidate_type} variant="footer" muted={muted} className="mt-auto" />
      : <SharePointOfferSource provenance={candidate.provenance} candidateType={candidate.candidate_type} className="mt-auto px-4 pb-4 pr-11" />}
    <button type="button" onClick={onInfo} aria-label={'Details for ' + name} title="Match details"
      className={'absolute right-3 rounded-full p-1.5 text-[#1B4E8A] hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-[#1B4E8A] ' + (offer ? 'bottom-12' : 'bottom-3')}>
      <Info size={17} />
    </button>
  </div>;
}

function SelectedCandidate({ candidate, onInfo }: { candidate: MatchCandidateV1; onInfo: () => void }) {
  const score = candidate.score_components.ranking_score;
  const offer = candidate.candidate_type === 'historical_offer';
  const status = getOfferStatus(candidate);
  const muted = offer && status.muted;
  const name = candidate.descriptions[0] || candidate.item_number || 'Supplier offer';
  const packSize = getCandidatePackSize(candidate);
  return <div className={"flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border-2 border-[#1B4E8A] px-4 py-3 " + (muted ? "bg-gray-100" : "bg-blue-50/40")}>
    <div className="order-1 flex shrink-0 items-center gap-2">
      <span className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-[#1B4E8A] bg-[#1B4E8A]"><span className="h-2 w-2 rounded-full bg-white" /></span>
      <span className="text-xl font-extrabold leading-none text-gray-900">{typeof score === 'number' ? formatRankingScore(score) : '—'}</span>
      <span className="text-xs text-gray-500">/100</span>
    </div>
    <div className="order-3 w-full min-w-0 sm:order-2 sm:w-auto sm:flex-1">
      <div className={"mb-1.5 flex items-start gap-2 text-sm font-bold " + (muted ? "text-gray-500" : "text-gray-900")}><span title={name} className="min-w-0 flex-1 line-clamp-2 break-words leading-snug">{name}</span>{offer && <span className="shrink-0"><OfferBadge candidate={candidate} /></span>}</div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {offer ? <>
          <span><span className="mr-1.5 font-semibold text-gray-400">SUPPLIER</span><span className="text-gray-700">{candidate.supplier || 'Not specified'}</span></span>
          <span><span className="mr-1.5 font-semibold text-gray-400">{candidate.unit_price != null ? 'UNIT PRICE' : 'PRICE'}</span><OfferPriceAndValidity candidate={candidate} /></span>
          <SharePointOfferSource provenance={candidate.provenance} candidateType={candidate.candidate_type} variant="compact" />
        </> : <>
          <span><span className="mr-1.5 font-semibold text-gray-400">ERP ID</span><span className="text-gray-700">{candidate.item_number || 'Not specified'}</span></span>
          <span><span className="mr-1.5 font-semibold text-gray-400">PACK SIZE</span><span className={packSize ? 'text-gray-700' : 'text-gray-400'} title={candidate.package?.package_label || candidate.packaging.basis || undefined}>{packSize || 'Not recorded'}</span></span>
          <span className="inline-flex gap-1.5"><span className="font-semibold text-gray-400">AVAIL.</span><CandidateAvailability candidate={candidate} /></span>
        </>}
      </div>
    </div>
    <div className="order-2 ml-auto flex items-center gap-2 sm:order-3">
      <button type="button" onClick={onInfo} aria-label={'Details for ' + name} className="rounded-full p-1.5 text-[#1B4E8A] hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"><Info size={17} /></button>
    </div>
  </div>;
}

export function SmartMatchingScreen({ requestId, onContinue }: Props) {
  useOfferDateRefresh();
  const [data, setData] = useState<SavedMatching | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<CandidateDetails>(null);
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  const scrollToItemRef = useRef<number | null>(null);
  const [visibleCount, setVisibleCount] = useState(() => typeof window !== 'undefined' && window.matchMedia(LARGE_SCREEN_QUERY).matches ? 3 : 4);
  const [savingItems, setSavingItems] = useState<Set<number>>(new Set());
  const [recentlySavedItems, setRecentlySavedItems] = useState<Set<number>>(new Set());
  const savedTimers = useRef<Map<number, number>>(new Map());
  const savingItemsRef = useRef<Set<number>>(new Set());
  const decisionVersion = useRef(0);
  const [finalizing, setFinalizing] = useState(false);
  const [showUndecided, setShowUndecided] = useState(false);

  useLayoutEffect(() => {
    const itemId = scrollToItemRef.current;
    if (itemId === null) return;
    scrollToItemRef.current = null;
    document.getElementById('match-item-' + itemId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [expandedItems]);

  useEffect(() => {
    const media = window.matchMedia(LARGE_SCREEN_QUERY);
    const updateVisibleCount = () => setVisibleCount(media.matches ? 3 : 4);
    updateVisibleCount();
    media.addEventListener('change', updateVisibleCount);
    return () => media.removeEventListener('change', updateVisibleCount);
  }, []);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      const version = decisionVersion.current;
      return getRequestMatching(requestId)
        .then(value => {
          if (active && savingItemsRef.current.size === 0 && version === decisionVersion.current) {
            setData(value);
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
    return () => {
      active = false;
      window.clearInterval(timer);
      savedTimers.current.forEach(timeout => window.clearTimeout(timeout));
      savedTimers.current.clear();
    };
  }, [requestId]);

  const choose = async (itemId: number, candidateId?: string) => {
    if (savingItemsRef.current.has(itemId)) return;
    decisionVersion.current += 1;
    const savedTimer = savedTimers.current.get(itemId);
    if (savedTimer) window.clearTimeout(savedTimer);
    savedTimers.current.delete(itemId);
    setRecentlySavedItems(previous => {
      const next = new Set(previous);
      next.delete(itemId);
      return next;
    });
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
      if (expandedItems.has(itemId)) scrollToItemRef.current = itemId;
      setExpandedItems(previous => {
        if (!previous.has(itemId)) return previous;
        const next = new Set(previous);
        next.delete(itemId);
        return next;
      });
      setRecentlySavedItems(previous => new Set(previous).add(itemId));
      savedTimers.current.set(itemId, window.setTimeout(() => {
        setRecentlySavedItems(previous => {
          const next = new Set(previous);
          next.delete(itemId);
          return next;
        });
        savedTimers.current.delete(itemId);
      }, 2500));
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

  const toggleExpand = (itemId: number) => {
    scrollToItemRef.current = itemId;
    setExpandedItems(previous => {
      const next = new Set(previous);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  };

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
    document.getElementById('match-item-' + itemId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  if (!data) return <div className="p-6"><LoadingPanel label="Loading saved matching results" /></div>;

  return <div className="mx-auto w-full p-6 pb-32 2xl:w-[80%]">
    <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-5"><WorkflowStepper currentStep="matching" /></div>
    <div className="mb-5">
      <h1>Smart Matching</h1>
      <p className="text-gray-500 text-sm mt-0.5">
        Review the suggestions and choose an article or supplier offer for each item, or mark it unmatched.
      </p>
    </div>
    {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
    {data.status === 'matching_failed' && <button onClick={() => void retry()} className="mb-4 flex items-center gap-2 px-4 py-2 bg-amber-100 text-amber-800 rounded-lg"><RefreshCw size={14} /> Retry failed items</button>}
    <div className="space-y-4">
      {data.lines.map(line => {
        const expanded = expandedItems.has(line.itemId);
        const visible = expanded ? line.candidates : line.candidates.slice(0, visibleCount);
        const selectedOutside = !expanded && line.candidates.slice(visibleCount).find(candidate => candidate.candidate_id === line.selectedCandidateId);
        return <section id={'match-item-' + line.itemId} key={line.itemId} className={'rounded-xl border-2 overflow-hidden scroll-mt-6 ' + (line.decisionType === 'no_match' ? 'bg-gray-100 border-gray-300' : 'bg-white border-gray-200')}>
          <div className={'px-5 py-3.5 border-b border-gray-200 flex items-center gap-3 ' + (line.decisionType === 'no_match' ? 'bg-gray-200/70' : 'bg-gray-50')}>
            <MapPin size={15} className="text-gray-400 flex-shrink-0" />
            <div className="flex-1 flex items-center gap-3 flex-wrap">
              <span className="text-sm text-gray-900 font-bold">{line.name}</span>
              <span className="text-sm text-gray-500">Qty: {line.quantity?.toLocaleString() ?? 'Not specified'} {line.unit}</span>
              <span className="text-xs text-gray-500 capitalize">{line.domain}</span>
            </div>
            <span className={'flex-shrink-0 px-2.5 py-1 rounded-full text-xs font-semibold ' + (line.decisionType === 'no_match' ? 'bg-orange-100 text-orange-800' : line.decisionType ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700')}>{selectionLabel(line)}</span>
          </div>
          <div className="p-5">
            {line.error && <div className="mb-3"><ErrorPanel message={line.error} /></div>}
            {(line.status === 'pending' || line.status === 'running') && <LoadingPanel label={line.status === 'running' ? 'Matching this item' : 'Waiting for matching worker'} />}
            {line.status === 'completed' && <>
              {line.candidates.length === 0 && <p className="text-sm text-gray-500">No candidates were found for this item.</p>}
              <div className={'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 ' + (line.decisionType === 'no_match' ? 'opacity-65' : '')}>
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
                <SelectedCandidate candidate={selectedOutside} onInfo={() => setDetails({ line, candidate: selectedOutside })} />
              </div>}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                {line.candidates.length > visibleCount && <button type="button" onClick={() => toggleExpand(line.itemId)} aria-expanded={expanded} className="flex items-center gap-1 text-sm text-[#1B4E8A] hover:underline">
                  {expanded ? <><ChevronUp size={14} /> Show fewer options</> : <><ChevronDown size={14} /> See {line.candidates.length - visibleCount} more options</>}
                </button>}
                <div className="flex flex-wrap items-center gap-3 ml-auto">
                  {savingItems.has(line.itemId) ? <span role="status" className="text-xs text-gray-500">Saving…</span>
                    : recentlySavedItems.has(line.itemId) && <span role="status" className="inline-flex items-center gap-1 text-xs text-green-700"><Check size={14} /> Decision saved</span>}
                  <button type="button" disabled={savingItems.has(line.itemId)} aria-pressed={line.decisionType === 'no_match'} onClick={() => void choose(line.itemId)} className={'inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-semibold bg-white shadow-sm transition-colors disabled:opacity-50 ' + (line.decisionType === 'no_match' ? 'text-[#1B4E8A] ring-2 ring-inset ring-[#1B4E8A]' : 'text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50')}><Ban size={16} /> Mark this item as unmatched</button>
                </div>
              </div>
            </>}
          </div>
        </section>;
      })}
    </div>
    <div className="fixed bottom-0 right-0 z-20 bg-white border-t border-gray-200 shadow-lg px-3 sm:px-6 py-3" style={{ left: 'var(--sidebar-width, 14rem)' }}>
      {showUndecided && undecided.length > 0 && <div className="absolute bottom-full right-6 w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-xl max-h-72 overflow-y-auto p-2 mb-2">
        <div className="px-3 py-2 text-sm font-semibold text-gray-900">Items still needing a decision</div>
        {undecided.map(line => <button key={line.itemId} onClick={() => jumpTo(line.itemId)} className="block w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-blue-50 text-[#1B4E8A]">
          <span className="block truncate">{line.name}</span><span className="text-xs text-gray-500">{line.status === 'completed' ? 'Choose an article or offer, or mark unmatched' : line.status}</span>
        </button>)}
      </div>}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-4 max-w-6xl mx-auto">
        <button onClick={() => setShowUndecided(value => !value)} className="text-sm text-[#1B4E8A] hover:underline text-left" aria-expanded={showUndecided}>
          {undecided.length ? undecided.length + ' of ' + data.total + ' items need a decision · View items' : 'All ' + data.total + ' items have a decision'}
        </button>
        <button disabled={savingItems.size > 0 || finalizing} onClick={() => void continueOrReview()} className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[#1B4E8A] text-white disabled:bg-gray-300 font-bold whitespace-nowrap">
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
        <SharePointOfferSource provenance={details.candidate.provenance} candidateType={details.candidate.candidate_type} className="mb-4" />
        <dl className="grid grid-cols-2 gap-3 text-sm mb-5">
          <div><dt className="text-gray-500">Requested item</dt><dd className="font-medium">{details.line.name}</dd></div>
          {details.candidate.item_number && <div><dt className="text-gray-500">Article number</dt><dd className="font-mono">{details.candidate.item_number}</dd></div>}
          {details.candidate.candidate_type === 'historical_offer' && <>
            <div><dt className="text-gray-500">Supplier</dt><dd>{details.candidate.supplier || 'Not specified'}</dd></div>
            <div><dt className="text-gray-500">{details.candidate.unit_price != null ? 'Unit price' : 'Offer price'}</dt><dd>{formatOfferPrice(details.candidate.price, details.candidate.currency, details.candidate.price_basis, details.candidate.unit_price, details.candidate.unit_price_unit)}</dd></div>
            <div><dt className="text-gray-500">{details.candidate.offer_valid_until ? 'Validity' : 'Offer age'}</dt><dd><OfferValidity candidate={details.candidate} /><OfferFollowUp candidate={details.candidate} /></dd></div>
          </>}
          {details.candidate.candidate_type !== 'historical_offer' && <div><dt className="text-gray-500">Availability</dt><dd><CandidateAvailability candidate={details.candidate} /></dd></div>}
          <div><dt className="text-gray-500">Automated checks</dt><dd>{details.candidate.review_status === 'pass' ? 'No configured issue found' : details.candidate.review_status.replace(/_/g, ' ')}</dd></div>
          {details.candidate.manufacturer && <div><dt className="text-gray-500">Manufacturer</dt><dd>{details.candidate.manufacturer}</dd></div>}
          <div><dt className="text-gray-500">Packaging</dt><dd>{details.candidate.packaging.basis || details.candidate.packaging.status.replace(/_/g, ' ')}</dd></div>
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
