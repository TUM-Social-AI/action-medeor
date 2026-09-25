import { useEffect, useState, type ReactNode } from 'react';
import { AlertCircle, ArrowLeft, CheckCircle2, Package, Pencil, Users, Warehouse } from 'lucide-react';
import { getRequestSummary, type SavedSummary } from '../api/workflow';
import { confirmPartner, updatePartner } from '../api/client';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { formatRankingScore } from '../features/matching/format-ranking-score';
import { WorkflowStepper } from './WorkflowStepper';

type Props = { requestId: string; onBack: () => Promise<void> };

function MetricCard({ icon, label, value, sub }: { icon: ReactNode; label: string; value: string; sub: string }) {
  return <div className="bg-white rounded-xl border border-gray-200 p-4">
    <div className="w-9 h-9 rounded-lg bg-blue-50 text-[#1B4E8A] flex items-center justify-center mb-3">{icon}</div>
    <div className="text-xs text-gray-500 font-semibold uppercase tracking-wide">{label}</div>
    <div className="text-2xl text-gray-900 font-extrabold mt-1">{value}</div>
    <div className="text-xs text-gray-400 mt-1">{sub}</div>
  </div>;
}

export function OrderSummaryScreen({ requestId, onBack }: Props) {
  const [data, setData] = useState<SavedSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [returning, setReturning] = useState(false);
  const [editingPartner, setEditingPartner] = useState(false);
  const [savingPartner, setSavingPartner] = useState(false);
  const [partnerDraft, setPartnerDraft] = useState({ partner: '', region: '', contact: '' });

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

  const availabilityConfirmed = data.items.filter(item => item.availability === 'on_hand_sufficient').length;
  return <div className="p-6">
    <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-6"><WorkflowStepper currentStep="summary" /></div>
    {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
    <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
      <div>
        <div className="flex items-center gap-3">
          <h1>Order Summary</h1>
          {data.status === 'finalized' && <span className="px-2.5 py-1 rounded-full bg-green-100 text-green-700 text-xs font-semibold">Finalized</span>}
        </div>
        <p className="text-gray-500 text-sm mt-0.5">Final review of saved matches for {data.partner || 'this partner'} · Request {data.requestId}</p>
      </div>
      <button disabled={returning} onClick={() => void returnToMatching()} className="flex items-center gap-2 px-4 py-2.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
        <ArrowLeft size={14} /> Back to Matching
      </button>
    </div>

    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <MetricCard icon={<Package size={18} />} label="Total line items" value={String(data.items.length)} sub="From the uploaded request" />
      <MetricCard icon={<CheckCircle2 size={18} />} label="Selected articles" value={String(data.matchedCount)} sub="Saved catalog decisions" />
      <MetricCard icon={<AlertCircle size={18} />} label="Unmatched lines" value={String(data.unmatchedCount)} sub="Explicitly marked unmatched" />
      <MetricCard icon={<Warehouse size={18} />} label="Stock confirmed" value={String(availabilityConfirmed)} sub="Availability sufficient for request" />
    </div>

    <div className="flex flex-col lg:flex-row gap-5">
      <div className="flex-1 min-w-0">
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200 bg-gray-50 flex items-center justify-between gap-3">
            <div className="text-sm text-gray-900 font-bold truncate">Matched Items · {data.sourceFile}</div>
            <div className="text-xs text-gray-400 whitespace-nowrap">Request ID: {data.requestId}</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px]">
              <thead><tr className="border-b border-gray-200">
                {['#', 'Requested Item', 'ERP Product', 'SKU', 'Qty', 'Ranking Score', 'Availability'].map(label => <th key={label} className="px-4 py-3 text-xs text-gray-500 text-left uppercase tracking-wide font-semibold">{label}</th>)}
              </tr></thead>
              <tbody>{data.items.map((item, index) => <tr key={item.itemId} className={'border-b border-gray-100 hover:bg-gray-50/60 ' + (!item.itemNumber ? 'bg-amber-50/40' : '')}>
                <td className="px-4 py-3.5 text-xs text-gray-400">{index + 1}</td>
                <td className="px-4 py-3.5 text-xs text-gray-700">{item.requested}</td>
                <td className="px-4 py-3.5 text-sm text-gray-900 font-semibold">{item.product || <span className="text-amber-700">Marked unmatched</span>}</td>
                <td className="px-4 py-3.5 text-xs text-gray-500 font-mono">{item.itemNumber || '—'}</td>
                <td className="px-4 py-3.5 text-sm text-gray-900 whitespace-nowrap">{item.quantity?.toLocaleString() ?? '—'} <span className="text-xs text-gray-400">{item.unit}</span></td>
                <td className="px-4 py-3.5 text-sm font-semibold text-gray-700 whitespace-nowrap">{typeof item.rankingScore === 'number' ? formatRankingScore(item.rankingScore) + '/100' : '—'}</td>
                <td className="px-4 py-3.5 text-xs text-gray-600">{item.availability?.replace(/_/g, ' ') ?? '—'}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </div>
        <p className="text-xs text-gray-500 mt-3">Ranking scores come from the matching evidence used to sort candidates. The best option for each item scores 100; compare scores only within the same requested item. Pricing and offer generation are not available yet.</p>
      </div>

      <aside className="w-full lg:w-64 flex-shrink-0">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between gap-2 mb-4">
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
            <dl className="space-y-3">
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
