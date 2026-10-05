import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { AlertCircle, ArrowLeft, CheckCircle2, FileDown, Maximize2, Package, Pencil, Users, Warehouse, X } from 'lucide-react';
import { getRequestSummary, type SavedSummary } from '../api/workflow';
import { fetchRequestResults, saveRequestResults } from '../api/export/client';
import { confirmPartner, updatePartner } from '../api/client';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { formatRankingScore } from '../features/matching/format-ranking-score';
import { formatOfferPrice, getOfferStatus } from '../features/matching/offer-display';
import { useOfferDateRefresh } from '../features/matching/use-offer-date-refresh';
import { WorkflowStepper } from './WorkflowStepper';
import { ProcessingProgress } from './ProcessingScreen';
import { SharePointOfferSource } from './SharePointOfferSource';
import { CandidateAvailability } from './CandidateAvailability';

type Props = { requestId: string; onBack: () => Promise<void> };

const EXPORT_STEPS = [
  'Creating results workbook',
  'Checking Excel file',
  'Preparing download',
] as const;

const showStep = (milliseconds: number) => new Promise<void>(resolve => window.setTimeout(resolve, milliseconds));

function MetricCard({ icon, label, value, sub }: { icon: ReactNode; label: string; value: string; sub: string }) {
  return <div className="flex items-center gap-3 bg-white rounded-xl border border-gray-200 px-3 py-2.5 sm:px-4">
    <div className="w-9 h-9 rounded-lg bg-blue-50 text-[#1B4E8A] flex flex-shrink-0 items-center justify-center">{icon}</div>
    <div className="min-w-0">
      <div className="text-[11px] leading-4 text-gray-500 font-semibold uppercase tracking-wide">{label}</div>
      <div className="text-xl leading-6 text-gray-900 font-extrabold tabular-nums">{value}</div>
      <div className="hidden sm:block truncate text-xs leading-4 text-gray-400" title={sub}>{sub}</div>
    </div>
  </div>;
}

export function OrderSummaryScreen({ requestId, onBack }: Props) {
  useOfferDateRefresh();
  const [data, setData] = useState<SavedSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [returning, setReturning] = useState(false);
  const [exportPhase, setExportPhase] = useState<'idle' | 'preparing' | 'ready' | 'error'>('idle');
  const [preparedFile, setPreparedFile] = useState<Blob | null>(null);
  const [exportStepsCompleted, setExportStepsCompleted] = useState(0);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportTriggerRef = useRef<HTMLButtonElement>(null);
  const exportDialogRef = useRef<HTMLDivElement>(null);
  const readyDownloadRef = useRef<HTMLButtonElement>(null);
  const [editingPartner, setEditingPartner] = useState(false);
  const [savingPartner, setSavingPartner] = useState(false);
  const [partnerDraft, setPartnerDraft] = useState({ partner: '', region: '', contact: '' });
  const [tableExpanded, setTableExpanded] = useState(false);
  const tableExpandRef = useRef<HTMLButtonElement>(null);
  const tableCloseRef = useRef<HTMLButtonElement>(null);
  const tableRegionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    getRequestSummary(requestId)
      .then(value => { if (active) { setData(value); setError(null); } })
      .catch(caught => { if (active) setError(String(caught)); });
    return () => { active = false; };
  }, [requestId]);

  const returnToMatching = async () => {
    setReturning(true);
    try {
      await onBack();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not reopen matching');
      setReturning(false);
    }
  };

  useEffect(() => {
    if (exportPhase === 'preparing' || exportPhase === 'error') exportDialogRef.current?.focus();
    if (exportPhase === 'ready') readyDownloadRef.current?.focus();
  }, [exportPhase]);

  const prepareResults = async () => {
    setPreparedFile(null);
    setExportStepsCompleted(0);
    setExportError(null);
    setExportPhase('preparing');
    try {
      // The API supplies a complete workbook. This also works if it later extends the source file.
      const file = await fetchRequestResults(requestId);
      setExportStepsCompleted(1);
      await showStep(350);

      const signature = new Uint8Array(await file.slice(0, 4).arrayBuffer());
      if (signature.length < 4 || signature[0] !== 0x50 || signature[1] !== 0x4b
        || signature[2] !== 0x03 || signature[3] !== 0x04) {
        throw new Error('The server did not return a valid Excel file. Please try again.');
      }
      setExportStepsCompleted(2);
      await showStep(350);

      setPreparedFile(file);
      setExportStepsCompleted(3);
      // Keep all three checkmarks visible before switching to the ready dialog.
      await showStep(650);
      setExportPhase('ready');
    } catch (caught) {
      setExportError(caught instanceof Error ? caught.message : 'Could not prepare Excel results');
      setExportPhase('error');
    }
  };

  const closeExport = () => {
    setExportPhase('idle');
    setPreparedFile(null);
    exportTriggerRef.current?.focus();
  };

  const handleExportKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && exportPhase !== 'preparing') closeExport();
    if (event.key !== 'Tab') return;
    const controls = Array.from(exportDialogRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
    if (controls.length === 0) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && document.activeElement === controls[0]) {
      event.preventDefault();
      controls[controls.length - 1].focus();
    } else if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) {
      event.preventDefault();
      controls[0].focus();
    }
  };

  useEffect(() => {
    if (!tableExpanded) return;
    tableCloseRef.current?.focus();
    const main = tableRegionRef.current?.closest('main');
    const previousOverflow = main?.style.overflow;
    if (main) main.style.overflow = 'hidden';
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setTableExpanded(false);
        window.requestAnimationFrame(() => (tableExpandRef.current ?? tableRegionRef.current)?.focus());
      }
      if (event.key !== 'Tab') return;
      if (event.shiftKey && document.activeElement === tableCloseRef.current) {
        event.preventDefault();
        tableRegionRef.current?.focus();
      } else if (!event.shiftKey && document.activeElement === tableRegionRef.current) {
        event.preventDefault();
        tableCloseRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (main) main.style.overflow = previousOverflow ?? '';
    };
  }, [tableExpanded]);

  const closeTable = () => {
    setTableExpanded(false);
    window.requestAnimationFrame(() => (tableExpandRef.current ?? tableRegionRef.current)?.focus());
  };

  const savePartner = async () => {
    if (!data) return;
    setSavingPartner(true);
    try {
      const updated = await updatePartner(requestId, { ...partnerDraft, requestId });
      setData({ ...data, partner: updated.partner, region: updated.region, contact: updated.contact, partnerConfirmed: updated.confirmed });
      setEditingPartner(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save partner details');
    } finally {
      setSavingPartner(false);
    }
  };

  const confirmPartnerDetails = async () => {
    if (!data) return;
    setSavingPartner(true);
    try {
      const updated = await confirmPartner(requestId);
      setData({ ...data, partner: updated.partner, region: updated.region, contact: updated.contact, partnerConfirmed: updated.confirmed });
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not confirm partner details');
    } finally {
      setSavingPartner(false);
    }
  };

  if (!data && !error) return <div className="p-6"><LoadingPanel label="Loading saved summary" /></div>;
  if (!data) return <div className="p-6"><ErrorPanel message={error ?? 'Summary unavailable'} /></div>;

  const availabilityConfirmed = data.items.filter(item => item.candidateType !== 'historical_offer' && item.availability === 'on_hand_sufficient').length;
  const supplierOffers = data.items.filter(item => item.candidateType === 'historical_offer');
  const offersWithoutPrice = supplierOffers.filter(item => item.unitPrice == null && item.price == null).length;
  const expiredOffers = supplierOffers.filter(item => getOfferStatus({ offer_valid_until: item.offerValidUntil }).expired).length;
  const oldOffers = supplierOffers.filter(item => {
    const status = getOfferStatus({ offer_valid_until: item.offerValidUntil, offer_date: item.offerDate });
    return status.muted && !status.expired;
  }).length;
  return <div className="px-6 py-4 max-w-7xl mx-auto min-w-0">
    <div className="bg-white rounded-xl border border-gray-200 px-5 py-3 mb-5"><WorkflowStepper currentStep="summary" /></div>
    {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
    <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
      <div>
        <div className="flex items-center gap-3">
          <h1>Order Summary</h1>
          {data.status === 'finalized' && <span className="px-2.5 py-1 rounded-full bg-green-100 text-green-700 text-xs font-semibold">Finalized</span>}
        </div>
        <p className="text-gray-500 text-sm mt-0.5">Final review of saved matches for {data.partner || 'this partner'} · Request {data.requestId}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={returning} onClick={() => void returnToMatching()} className="flex items-center gap-2 px-4 py-2.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
          <ArrowLeft size={14} /> Back to Matching
        </button>
        <button ref={exportTriggerRef} type="button" disabled={exportPhase !== 'idle'} onClick={() => void prepareResults()} className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-[#009E91] text-white text-sm font-semibold hover:bg-[#00877D] disabled:opacity-50">
          <FileDown size={16} /> Download Excel
        </button>
      </div>
    </div>

    {exportPhase !== 'idle' && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-gray-950/50 p-4">
      <div ref={exportDialogRef} role="dialog" aria-modal="true" aria-labelledby="export-dialog-title" aria-describedby="export-dialog-description" tabIndex={-1} onKeyDown={handleExportKeyDown} className={"w-full max-w-md rounded-2xl bg-white shadow-2xl focus:outline-none " + (exportPhase === 'preparing' ? 'border border-gray-100 p-10' : 'p-8')}>
        {exportPhase === 'preparing' ? <div role="status" aria-live="polite">
          <ProcessingProgress
            title="Preparing Excel file"
            subtitle={`Preparing ${data.items.length} saved results and request details for your download.`}
            steps={EXPORT_STEPS}
            completedSteps={exportStepsCompleted}
            accentColor="#1B4E8A"
            iconBg="bg-blue-50"
            titleId="export-dialog-title"
            subtitleId="export-dialog-description"
          />
          <span className="sr-only">{exportStepsCompleted} of {EXPORT_STEPS.length} steps complete</span>
        </div> : exportPhase === 'ready' ? <>
          <div className="flex items-start justify-between gap-3">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-teal-50 text-[#009E91]"><CheckCircle2 size={28} /></div>
            <button type="button" onClick={closeExport} aria-label="Close download dialog" className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"><X size={18} /></button>
          </div>
          <h2 id="export-dialog-title" className="mt-5 text-lg font-bold text-gray-900">Excel file ready</h2>
          <p id="export-dialog-description" className="mt-1 text-sm text-gray-500 break-all">matched-results-{data.requestId}.xlsx</p>
          <p className="mt-1 text-xs text-gray-400">{data.items.length} line items · {data.matchedCount} matched · {data.unmatchedCount} unmatched</p>
          <button ref={readyDownloadRef} type="button" onClick={() => { if (preparedFile) saveRequestResults(preparedFile, requestId); }} className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-[#1B4E8A] px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-[#173F70]">
            <FileDown size={16} /> Download Excel
          </button>
          <button type="button" onClick={closeExport} className="mt-3 w-full rounded-lg py-2 text-sm text-gray-500 hover:bg-gray-50">Close</button>
        </> : <>
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-50 text-red-600"><AlertCircle size={28} /></div>
          <h2 id="export-dialog-title" className="mt-5 text-lg font-bold text-gray-900">Excel file unavailable</h2>
          <p id="export-dialog-description" className="mt-1 text-sm text-gray-500">{exportError}</p>
          <button type="button" onClick={() => void prepareResults()} className="mt-6 w-full rounded-xl bg-[#1B4E8A] px-4 py-3 text-sm font-semibold text-white hover:bg-[#173F70]">Try again</button>
          <button type="button" onClick={closeExport} className="mt-3 w-full rounded-lg py-2 text-sm text-gray-500 hover:bg-gray-50">Close</button>
        </>}
      </div>
    </div>}

    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
      <MetricCard icon={<Package size={18} />} label="Total line items" value={String(data.items.length)} sub={supplierOffers.length ? `${data.items.length - supplierOffers.length} other lines · ${supplierOffers.length} supplier offers` : 'From the uploaded request'} />
      <MetricCard icon={<CheckCircle2 size={18} />} label="Selected matches" value={String(data.matchedCount)} sub="Saved article and offer decisions" />
      <MetricCard icon={<AlertCircle size={18} />} label="Unmatched lines" value={String(data.unmatchedCount)} sub="Explicitly marked unmatched" />
      <MetricCard icon={<Warehouse size={18} />} label="Stock confirmed" value={String(availabilityConfirmed)} sub="Availability sufficient for request" />
    </div>

    <div className="flex flex-col lg:flex-row gap-5">
      <div className="flex-1 min-w-0">
        <div className={tableExpanded ? 'fixed inset-0 z-[60] bg-gray-950/50 p-2 sm:p-4' : ''}>
          <div role={tableExpanded ? 'dialog' : undefined} aria-modal={tableExpanded ? true : undefined} aria-labelledby="summary-table-title" className={'bg-white rounded-xl border border-gray-200 overflow-hidden ' + (tableExpanded ? 'flex h-full flex-col shadow-2xl' : '')}>
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between gap-3 sm:px-5">
            <div id="summary-table-title" className="text-sm text-gray-900 font-bold truncate">Matched Items · {data.sourceFile}</div>
            <div className="flex flex-shrink-0 items-center gap-3">
              <div className="hidden sm:block text-xs text-gray-400 whitespace-nowrap">Request ID: {data.requestId}</div>
              {tableExpanded ? <button ref={tableCloseRef} type="button" onClick={closeTable} aria-label="Close expanded table" className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"><X size={14} /> Close</button> : <button ref={tableExpandRef} type="button" onClick={() => setTableExpanded(true)} aria-label="Expand matched items table" className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"><Maximize2 size={14} /> Expand</button>}
            </div>
          </div>
          <div ref={tableRegionRef} role="region" aria-label="Matched items table" tabIndex={0} className={'max-w-full overflow-auto overscroll-contain focus-visible:outline-2 focus-visible:outline-[#1B4E8A] ' + (tableExpanded ? 'min-h-0 flex-1' : 'max-h-[max(14rem,calc(100dvh-28rem))]')}>
            <table className="w-full min-w-[1120px] text-sm text-gray-700">
              <thead className="sticky top-0 z-10 bg-gray-50"><tr className="border-b border-gray-200">
                {['#', 'Requested Item', 'Matched Product', 'ERP SKU / Offer', 'Qty', 'Ranking Score', 'Availability', 'Offer price'].map(label => <th key={label} className="px-4 py-3 text-xs text-gray-500 text-left uppercase tracking-wide font-semibold whitespace-nowrap">{label}</th>)}
              </tr></thead>
              <tbody>{data.items.map((item, index) => {
                const isOffer = item.candidateType === 'historical_offer';
                const offerStatus = isOffer ? getOfferStatus({ offer_valid_until: item.offerValidUntil, offer_date: item.offerDate }) : null;
                return <tr key={item.itemId} className={'border-b transition-colors ' + (isOffer
                  ? offerStatus?.muted ? 'border-rose-200 bg-rose-50 hover:bg-rose-100/70' : 'border-violet-100 bg-violet-50/50 hover:bg-violet-50'
                  : item.decision === 'no_match' ? 'border-gray-100 bg-amber-50/40 hover:bg-amber-50/60'
                    : 'border-gray-100 hover:bg-gray-50/60')}>
                  <td className={'border-l-[3px] px-4 py-3 text-gray-500 tabular-nums ' + (offerStatus?.muted ? 'border-l-rose-500' : isOffer ? 'border-l-violet-500' : 'border-l-transparent')}>{index + 1}{offerStatus?.muted && <span className="sr-only">, {offerStatus.expired ? 'expired' : 'six months or older'} supplier offer</span>}</td>
                  <td className="px-4 py-3 text-gray-800">{item.requested}</td>
                  <td className="px-4 py-3 text-gray-900">
                    <div className="font-semibold">{item.product || <span className="text-amber-700">Marked unmatched</span>}</div>
                    {isOffer ? <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-violet-700">
                      {item.supplier && <span>{item.supplier}</span>}
                    </div> : <SharePointOfferSource provenance={item.provenance ?? []} candidateType={item.candidateType} className="mt-1" />}
                  </td>
                  <td className="max-w-[180px] px-4 py-3">
                    {isOffer ? <SharePointOfferSource provenance={item.provenance ?? []} candidateType={item.candidateType} variant="compact" />
                      : <span className="font-mono text-xs text-gray-600">{item.itemNumber || '—'}</span>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-900 tabular-nums">{item.quantity?.toLocaleString() ?? '—'} <span className="text-gray-500">{item.unit}</span></td>
                  <td className="whitespace-nowrap px-4 py-3 font-semibold text-gray-700 tabular-nums">{typeof item.rankingScore === 'number' ? formatRankingScore(item.rankingScore) + '/100' : '—'}</td>
                  <td className="px-4 py-3">{isOffer ? <span className="text-gray-400">—</span>
                    : item.availability ? <CandidateAvailability candidate={{ available_quantity: item.availableQuantity, required_stock_quantity: item.requiredStockQuantity, stock_unit: item.stockUnit, availability_status: item.availability }} /> : <span className="text-gray-700">—</span>}</td>
                  <td className="px-4 py-3 text-xs">{isOffer ? <span><span className={offerStatus?.muted ? 'text-gray-400 line-through' : item.unitPrice == null && item.price == null ? 'italic text-gray-400' : 'font-semibold text-violet-800'}>{formatOfferPrice(item.price, item.currency, item.priceBasis, item.unitPrice, item.unitPriceUnit)}</span><span className="text-gray-400"> · </span><span className={offerStatus?.warning ? 'font-semibold text-red-700' : 'text-gray-700'}>{offerStatus?.label}</span></span> : <span className="text-gray-400">—</span>}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>
          </div>
        </div>
        <p className="text-xs text-gray-500 mt-3">Ranking scores come from the matching evidence used to sort candidates. The best option for each item scores 100; compare scores only within the same requested item. Offer prices are shown when they are recorded; quote generation is not available yet.</p>
      </div>

      <aside className="w-full lg:w-64 flex-shrink-0">
        {supplierOffers.length > 0 && <div className="mb-4 flex items-start gap-2 rounded-xl border border-violet-200 bg-violet-50 p-3 text-xs leading-snug text-violet-900">
          <AlertCircle size={16} className="mt-0.5 shrink-0 text-violet-600" />
          <p><span className="font-bold">{supplierOffers.length} supplier {supplierOffers.length === 1 ? 'offer' : 'offers'} selected.</span>{expiredOffers > 0 && ` ${expiredOffers} expired.`}{oldOffers > 0 && ` ${oldOffers} at least six months old without an expiry date.`} Check terms with the supplier before ordering.{offersWithoutPrice > 0 && ` ${offersWithoutPrice} without a recorded price.`}</p>
        </div>}
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="flex items-center gap-2"><Users size={15} className="text-gray-400" /><h2 className="text-sm text-gray-900 font-semibold">Partner & Request Details</h2></div>
            {!data.partnerConfirmed && !editingPartner && <button type="button" title="Edit partner details" aria-label="Edit partner details" onClick={() => { setPartnerDraft({ partner: data.partner, region: data.region, contact: data.contact }); setEditingPartner(true); }} className="p-1 rounded text-gray-500 hover:bg-gray-100"><Pencil size={14} /></button>}
          </div>
          {editingPartner ? <div className="space-y-3">
            {(['partner', 'region', 'contact'] as const).map(key => <label key={key} className="block text-xs text-gray-500">
              <span className="block mb-1">{key === 'partner' ? 'Organization' : key === 'region' ? 'Region' : 'Contact'}</span>
              <input value={partnerDraft[key]} onChange={event => setPartnerDraft(draft => ({ ...draft, [key]: event.target.value }))} className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-xs text-gray-900" />
            </label>)}
            <div className="text-xs text-gray-500">System request ID: <span className="font-mono text-gray-700">{data.requestId}</span></div>
            <div className="flex gap-2 pt-1">
              <button type="button" disabled={savingPartner} onClick={() => setEditingPartner(false)} className="flex-1 rounded-lg border border-gray-200 px-2 py-1.5 text-xs">Cancel</button>
              <button type="button" disabled={savingPartner} onClick={() => void savePartner()} className="flex-1 rounded-lg bg-[#1B4E8A] px-2 py-1.5 text-xs font-semibold text-white disabled:opacity-50">Save</button>
            </div>
          </div> : <>
            <dl className="space-y-1.5">
              {[
                { label: 'Organization', value: data.partner },
                { label: 'Region', value: data.region },
                { label: 'Request ID', value: data.requestId },
                { label: 'Contact', value: data.contact },
                { label: 'Request date', value: data.requestDate },
                { label: 'Source file', value: data.sourceFile },
              ].map(row => <div key={row.label}><dt className="text-xs text-gray-400">{row.label}</dt><dd className="text-xs text-gray-800 font-medium break-words">{row.value || 'Not specified'}</dd></div>)}
            </dl>
            {data.partnerConfirmed ? <div className="mt-4 flex items-center gap-1.5 text-xs font-medium text-green-700"><CheckCircle2 size={14} /> Details confirmed</div> :
              <button type="button" disabled={savingPartner} onClick={() => void confirmPartnerDetails()} className="mt-4 w-full rounded-lg bg-[#1B4E8A] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Confirm Details</button>}
          </>}
        </div>
      </aside>
    </div>
  </div>;
}
