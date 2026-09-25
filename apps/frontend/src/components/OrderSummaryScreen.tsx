import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { getRequestSummary, type SavedSummary } from '../api/workflow';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

export function OrderSummaryScreen({ requestId, onBack }: { requestId: string; onBack: () => void }) {
  const [data, setData] = useState<SavedSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getRequestSummary(requestId)
      .then(value => { if (active) setData(value); })
      .catch(caught => { if (active) setError(String(caught)); });
    return () => { active = false; };
  }, [requestId]);
  if (!data && !error) return <div className="p-6"><LoadingPanel label="Loading saved summary" /></div>;
  if (!data) return <div className="p-6"><ErrorPanel message={error ?? 'Summary unavailable'} /></div>;
  return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-5"><WorkflowStepper currentStep="summary" /></div>
      <div className="flex justify-between mb-5">
        <div>
          <h1 className="text-gray-900">Request Summary</h1>
          <p className="text-sm text-gray-500">{data.requestId} · {data.sourceFile} · {data.partner || 'Partner not specified'}</p>
        </div>
        <button onClick={onBack} className="flex items-center gap-2 border rounded-lg px-4 py-2 text-sm"><ArrowLeft size={14} /> Back to Matching</button>
      </div>
      <p className="text-sm text-gray-700 mb-4">{data.matchedCount} matched · {data.unmatchedCount} unmatched</p>
      <div className="bg-white border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50"><tr>{['Requested item', 'Quantity', 'Selected article', 'Availability', 'Evidence'].map(label => <th key={label} className="text-left p-3">{label}</th>)}</tr></thead>
          <tbody>{data.items.map(item => <tr key={item.itemId} className="border-t">
            <td className="p-3">{item.requested}</td>
            <td className="p-3">{item.quantity ?? '—'} {item.unit}</td>
            <td className="p-3">{item.itemNumber ? `${item.product} (${item.itemNumber})` : 'No match'}</td>
            <td className="p-3">{item.availability?.replace(/_/g, ' ') ?? '—'}</td>
            <td className="p-3">{item.retrievalMethods.join(', ') || '—'}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500 mt-4">Pricing and offer generation are not available for this request yet.</p>
    </div>
  );
}
