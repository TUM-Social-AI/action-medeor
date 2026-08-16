import { useEffect, useState } from 'react';
import { ArrowRight, ChevronDown, ChevronUp, MapPin } from 'lucide-react';
import type {
  MatchCandidateView,
  MatchingScreenView,
  MatchingWorkflowApi,
  RequestedLineView,
} from '../features/matching/models';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type SmartMatchingScreenProps = {
  requestId: string;
  initialData?: MatchingScreenView | null;
  api: MatchingWorkflowApi;
  onContinue: () => void;
};

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-yellow-100 text-yellow-700',
};

const VISIBLE_COUNT = 3;

export function SmartMatchingScreen({ requestId, initialData, api, onContinue }: SmartMatchingScreenProps) {
  const [data, setData] = useState<MatchingScreenView | null>(initialData ?? null);
  const [selectedMatches, setSelectedMatches] = useState<Record<string, string>>(
    initialData?.selectedCandidateIdsByLine ?? {},
  );
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(!initialData);

  useEffect(() => {
    if (initialData) {
      setData(initialData);
      setSelectedMatches(initialData.selectedCandidateIdsByLine);
      setIsLoading(false);
      return;
    }

    let mounted = true;
    setIsLoading(true);
    api.start(requestId)
      .then(response => {
        if (mounted) {
          setData(response);
          setSelectedMatches(response.selectedCandidateIdsByLine);
          setError(null);
        }
      })
      .catch(caught => {
        if (mounted) {
          setError(caught instanceof Error ? caught.message : 'Unable to reach backend');
        }
      })
      .finally(() => {
        if (mounted) {
          setIsLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [api, initialData, requestId]);

  const selectMatch = async (lineId: string, candidateId: string) => {
    const previousSelection = selectedMatches[lineId];
    setSelectedMatches(prev => ({ ...prev, [lineId]: candidateId }));

    try {
      await api.selectCandidate(requestId, lineId, candidateId);
      setError(null);
    } catch (caught) {
      setSelectedMatches(prev => {
        const next = { ...prev };
        if (previousSelection) next[lineId] = previousSelection;
        else delete next[lineId];
        return next;
      });
      setError(caught instanceof Error ? caught.message : 'Unable to update selected match');
    }
  };

  const toggleExpand = (itemId: string) =>
    setExpandedItems(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });

  if (isLoading) {
    return (
      <div className="p-6">
        <LoadingPanel label="Loading ERP match candidates" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6">
        <ErrorPanel message={error ?? 'Matching data is unavailable'} />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-5">
        <WorkflowStepper currentStep="matching" />
      </div>

      {error && <div className="mb-4"><ErrorPanel message={error} /></div>}

      <div className="mb-5">
        <h1 className="text-gray-900">Smart Matching</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          Review and adjust ERP product matches for each requested item. Best-fit options are
          pre-selected. Scroll through all items and click Continue at the bottom.
        </p>
      </div>

      <div className="space-y-4">
        {data.requestedLines.map(item => (
          <MatchingItem
            key={item.id}
            item={item}
            matches={data.candidatesByLine[item.id] ?? []}
            selectedId={selectedMatches[item.id]}
            lineError={data.errorsByLine[item.id]}
            isExpanded={expandedItems.has(item.id)}
            onToggleExpand={() => toggleExpand(item.id)}
            onSelect={candidateId => void selectMatch(item.id, candidateId)}
          />
        ))}
      </div>

      <div className="mt-8 flex justify-end">
        <button
          onClick={onContinue}
          className="flex items-center gap-2 px-8 py-3 bg-[#1B4E8A] text-white rounded-xl hover:bg-[#163d6d] transition-colors shadow-md"
          style={{ fontWeight: 700 }}
        >
          Continue to Order Summary
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

function MatchingItem({
  item,
  matches,
  selectedId,
  lineError,
  isExpanded,
  onToggleExpand,
  onSelect,
}: {
  item: RequestedLineView;
  matches: MatchCandidateView[];
  selectedId?: string;
  lineError?: string;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onSelect: (matchId: string) => void;
}) {
  const hasMore = matches.length > VISIBLE_COUNT;
  const topMatches = matches.slice(0, VISIBLE_COUNT);
  const visibleMatches = isExpanded ? matches : topMatches;
  const selectedIndex = matches.findIndex(match => match.id === selectedId);
  const extraSelectedMatch = !isExpanded && selectedIndex >= VISIBLE_COUNT ? matches[selectedIndex] : null;

  return (
    <div className="bg-white rounded-xl border-2 border-gray-200 overflow-hidden">
      <div className="px-5 py-3.5 bg-gray-50 border-b border-gray-200 flex items-center gap-3">
        <MapPin size={15} className="text-gray-400 flex-shrink-0" />
        <div className="flex-1 flex items-center gap-3 flex-wrap">
          <span className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
            {item.name}
          </span>
          <span className="text-sm text-gray-400">
            Qty: {item.quantity?.toLocaleString() ?? 'Not specified'} {item.unit}
          </span>
          <span className="text-gray-300">-</span>
          <span className="text-sm text-gray-500">
            Priority:{' '}
            <span
              className={`text-xs px-1.5 py-0.5 rounded-full ${PRIORITY_COLOR[item.priority ?? 'medium']}`}
              style={{ fontWeight: 600 }}
            >
              {item.priority ?? 'not set'}
            </span>
          </span>
        </div>
        <span className="flex-shrink-0 px-2.5 py-1 bg-blue-100 text-blue-700 rounded-full text-xs" style={{ fontWeight: 600 }}>
          VERIFIED REQUEST
        </span>
      </div>

      <div className="p-5">
        {lineError && <div className="mb-3"><ErrorPanel message={lineError} /></div>}
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: `repeat(${Math.min(visibleMatches.length, VISIBLE_COUNT)}, 1fr)` }}
        >
          {visibleMatches.map(match => (
            <MatchCard
              key={match.id}
              match={match}
              isBestFit={matches.indexOf(match) === 0}
              isSelected={selectedId === match.id}
              onSelect={() => onSelect(match.id)}
            />
          ))}
        </div>

        {extraSelectedMatch && (
          <div className="mt-4">
            <div className="flex items-center gap-2 mb-2.5">
              <div className="flex-1 h-px bg-gray-200" />
              <span className="text-xs text-gray-400 px-1 whitespace-nowrap">Your current selection</span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>
            <div
              onClick={() => onSelect(extraSelectedMatch.id)}
              className="border-2 border-[#1B4E8A] rounded-xl p-3.5 bg-blue-50/40 flex items-center gap-5 cursor-pointer hover:bg-blue-50/60 transition-colors"
            >
              <div className="flex items-center gap-2 flex-shrink-0">
                <div className="w-5 h-5 rounded-full border-2 border-[#1B4E8A] bg-[#1B4E8A] flex items-center justify-center">
                  <div className="w-2 h-2 rounded-full bg-white" />
                </div>
                <span className="text-xl text-gray-900" style={{ fontWeight: 800, lineHeight: 1 }}>
                  #{extraSelectedMatch.rank}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-900 mb-1.5" style={{ fontWeight: 700 }}>
                  {extraSelectedMatch.name}
                </div>
                <MatchDetails match={extraSelectedMatch} compact />
              </div>
              <span className="flex-shrink-0 px-2.5 py-1 bg-[#1B4E8A] text-white rounded-full text-xs" style={{ fontWeight: 700 }}>
                SELECTED
              </span>
            </div>
          </div>
        )}

        {hasMore && (
          <div className="mt-3">
            <button
              onClick={onToggleExpand}
              className="flex items-center gap-1 text-sm text-[#1B4E8A] hover:underline"
              style={{ fontWeight: 500 }}
            >
              {isExpanded ? (
                <>
                  <ChevronUp size={14} /> Show fewer options
                </>
              ) : (
                <>
                  <ChevronDown size={14} /> See {matches.length - VISIBLE_COUNT} more option
                  {matches.length - VISIBLE_COUNT > 1 ? 's' : ''}
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function MatchCard({
  match,
  isBestFit,
  isSelected,
  onSelect,
}: {
  match: MatchCandidateView;
  isBestFit: boolean;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`text-left border-2 rounded-xl p-4 cursor-pointer transition-all select-none ${
        isSelected ? 'border-[#1B4E8A] bg-blue-50/40 shadow-sm' : 'border-gray-200 hover:border-gray-300 hover:shadow-sm'
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
              isSelected ? 'border-[#1B4E8A] bg-[#1B4E8A]' : 'border-gray-300'
            }`}
          >
            {isSelected && <div className="w-2 h-2 rounded-full bg-white" />}
          </div>
          <span className="text-2xl leading-none text-gray-900" style={{ fontWeight: 800 }}>
            #{match.rank}
          </span>
        </div>
        <div className="flex flex-col items-end gap-1">
          {isBestFit && (
            <span className="px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded text-xs" style={{ fontWeight: 700 }}>
              BEST FIT
            </span>
          )}
          <ReviewBadge status={match.reviewStatus} />
          <AvailabilityBadge status={match.availabilityStatus} />
        </div>
      </div>
      <div className="text-sm text-gray-900 mb-3 leading-snug" style={{ fontWeight: 700 }}>
        {match.name}
      </div>
      <MatchDetails match={match} />
      {(match.constraintMessages[0] || match.warnings[0]) && (
        <p className="mt-3 text-xs text-amber-700 leading-snug">
          {match.constraintMessages[0] ?? match.warnings[0]}
        </p>
      )}
    </button>
  );
}

function MatchDetails({ match, compact }: { match: MatchCandidateView; compact?: boolean }) {
  const rows = [
    { label: 'SKU', value: match.itemNumber, mono: true },
    { label: 'MFR', value: match.manufacturer },
    {
      label: 'AVAIL.',
      value: match.availabilityDetail ?? availabilityLabel(match.availabilityStatus),
      highlight: match.availabilityStatus === 'on_hand_sufficient' ? 'green' : 'red',
    },
  ].filter(row => row.value);

  if (compact) {
    return (
      <div className="flex flex-wrap gap-4">
        {rows.map(row => (
          <div key={row.label} className="flex items-center gap-1.5">
            <span className="text-gray-400" style={{ fontSize: 11, fontWeight: 600 }}>
              {row.label}
            </span>
            <span
              className={`text-xs ${
                row.highlight === 'red'
                  ? 'text-red-600'
                  : row.highlight === 'green'
                    ? 'text-green-700'
                    : 'text-gray-700'
              } ${row.mono ? 'font-mono' : ''}`}
              style={{ fontWeight: row.highlight ? 700 : 500 }}
            >
              {row.value}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {rows.map(row => (
        <div key={row.label} className="flex items-start gap-2">
          <span className="text-gray-400 flex-shrink-0" style={{ fontSize: 11, fontWeight: 600, width: 36, paddingTop: 1 }}>
            {row.label}
          </span>
          <span
            className={`text-xs break-all ${
              row.highlight === 'red'
                ? 'text-red-600'
                : row.highlight === 'green'
                  ? 'text-green-700'
                  : 'text-gray-700'
            } ${row.mono ? 'font-mono' : ''}`}
            style={{ fontWeight: row.highlight ? 700 : 500 }}
          >
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function ReviewBadge({ status }: { status: MatchCandidateView['reviewStatus'] }) {
  if (status === 'unknown') return null;
  const style = status === 'pass' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700';
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs ${style}`} style={{ fontWeight: 700 }}>
      {status.toUpperCase()}
    </span>
  );
}

function AvailabilityBadge({ status }: { status: MatchCandidateView['availabilityStatus'] }) {
  if (status === 'on_hand_sufficient' || status === 'unknown') return null;
  return (
    <span className="px-1.5 py-0.5 bg-red-100 text-red-600 rounded text-xs" style={{ fontWeight: 700 }}>
      {availabilityLabel(status).toUpperCase()}
    </span>
  );
}

function availabilityLabel(status: MatchCandidateView['availabilityStatus']) {
  return status.replace(/_/g, ' ');
}
