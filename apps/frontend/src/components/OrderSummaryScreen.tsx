import { useEffect, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Euro,
  FileDown,
  Loader2,
  Package,
  Pencil,
  Star,
  Users,
  X,
} from 'lucide-react';
import { createOffer, getSummary } from '../api/client';
import type { OfferResponse, PartnerDetails, SummaryResponse } from '../api/types';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type OfferState = 'idle' | 'generating' | 'ready';

export function OrderSummaryScreen({ requestId, onBack }: { requestId: string; onBack: () => void }) {
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [partnerConfirmed, setPartnerConfirmed] = useState(false);
  const [editingPartner, setEditingPartner] = useState(false);
  const [partnerData, setPartnerData] = useState<PartnerDetails | null>(null);
  const [partnerDraft, setPartnerDraft] = useState<PartnerDetails | null>(null);
  const [offerState, setOfferState] = useState<OfferState>('idle');
  const [offer, setOffer] = useState<OfferResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setIsLoading(true);

    getSummary(requestId)
      .then(response => {
        if (mounted) {
          setData(response);
          setPartnerData(response.partner);
          setPartnerConfirmed(response.partner.confirmed);
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
  }, [requestId]);

  const handleCreateOffer = async () => {
    setOfferState('generating');
    setError(null);

    try {
      const response = await createOffer(requestId);
      setOffer(response);
      setTimeout(() => setOfferState('ready'), 900);
    } catch (caught) {
      setOfferState('idle');
      setError(caught instanceof Error ? caught.message : 'Unable to create offer');
    }
  };

  if (isLoading) {
    return (
      <div className="p-6">
        <LoadingPanel label="Loading order summary" />
      </div>
    );
  }

  if (!data || !partnerData) {
    return (
      <div className="p-6">
        <ErrorPanel message={error ?? 'Summary data is unavailable'} />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-6">
        <WorkflowStepper currentStep="summary" />
      </div>

      {error && <div className="mb-4"><ErrorPanel message={error} /></div>}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-gray-900">Order Summary</h1>
          <p className="text-gray-500 text-sm mt-0.5">
            Final review of all matched items before generating the offer for {partnerData.partner} -
            Request {data.requestId}.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex items-center gap-2 px-4 py-2.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            style={{ fontWeight: 500 }}
          >
            <ArrowLeft size={14} />
            Back to Matching
          </button>
          <button
            onClick={() => void handleCreateOffer()}
            className="flex items-center gap-2 px-6 py-2.5 bg-[#0E9E8F] text-white rounded-lg text-sm hover:bg-[#0c8a7d] transition-colors shadow-md"
            style={{ fontWeight: 700 }}
          >
            <FileDown size={15} />
            Create Offer
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard
          icon={<Package size={18} className="text-[#1B4E8A]" />}
          label="Total Line Items"
          value={`${data.metrics.totalLineItems}`}
          sub="Across 8 product categories"
          iconBg="bg-blue-100"
        />
        <MetricCard
          icon={<CheckCircle2 size={18} className="text-[#0E9E8F]" />}
          label="High Confidence Matches"
          value={`${data.metrics.highConfidenceMatches} / ${data.metrics.totalLineItems}`}
          sub=">= 90% ERP match score"
          iconBg="bg-teal-100"
        />
        <MetricCard
          icon={<Star size={18} className="text-amber-600" />}
          label="Avg. Match Score"
          value={`${data.metrics.averageMatchScore}%`}
          sub="Across all matched items"
          iconBg="bg-amber-100"
        />
        <MetricCard
          icon={<Euro size={18} className="text-green-600" />}
          label="Est. Total Value"
          value={`EUR ${formatCurrency(data.metrics.estimatedTotalValue)}`}
          sub="Based on current ERP pricing"
          iconBg="bg-green-100"
        />
      </div>

      <div className="flex gap-5">
        <div className="flex-1 min-w-0">
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
              <div className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
                Matched Items - {data.sourceFile}
              </div>
              <div className="text-xs text-gray-400">Request ID: {data.requestId}</div>
            </div>
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  {['#', 'Requested Item', 'ERP Product', 'SKU', 'Qty', 'Match', 'Stock', 'Total (EUR)'].map(header => (
                    <th
                      key={header}
                      className={`px-4 py-3 text-xs text-gray-500 ${
                        ['Qty', 'Total (EUR)'].includes(header) ? 'text-right' : 'text-left'
                      }`}
                      style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item, index) => (
                  <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3.5 text-xs text-gray-400">{index + 1}</td>
                    <td className="px-4 py-3.5">
                      <span className="text-xs text-gray-500">{item.requested}</span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="text-sm text-gray-900" style={{ fontWeight: 600 }}>
                        {item.erpProduct}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="text-xs text-gray-500 font-mono">{item.sku}</span>
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <span className="text-sm text-gray-900" style={{ fontWeight: 600 }}>
                        {item.quantity.toLocaleString()}
                      </span>{' '}
                      <span className="text-xs text-gray-400">{item.unit}</span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded-full text-xs ${
                          item.matchScore >= 97
                            ? 'bg-green-100 text-green-700'
                            : item.matchScore >= 90
                              ? 'bg-teal-100 text-teal-700'
                              : 'bg-amber-100 text-amber-700'
                        }`}
                        style={{ fontWeight: 700 }}
                      >
                        {item.matchScore}%
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`text-xs ${item.stock === 'In Stock' ? 'text-green-600' : 'text-amber-600'}`}
                        style={{ fontWeight: 600 }}
                      >
                        {item.stock}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <span className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
                        {(item.pricePerUnit * item.quantity).toFixed(2)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-gray-50 border-t-2 border-gray-200">
                  <td colSpan={7} className="px-4 py-4 text-sm text-gray-600 text-right" style={{ fontWeight: 600 }}>
                    Estimated Total Value (EUR)
                  </td>
                  <td className="px-4 py-4 text-right">
                    <span className="text-base text-gray-900" style={{ fontWeight: 800 }}>
                      {formatCurrency(data.metrics.estimatedTotalValue)}
                    </span>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        <div className="w-64 flex-shrink-0">
          <div className={`rounded-xl border p-5 ${partnerConfirmed ? 'bg-white border-green-200' : 'bg-amber-50 border-amber-300'}`}>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <Users size={15} className={partnerConfirmed ? 'text-gray-400' : 'text-amber-500'} />
                <h3 className="text-sm text-gray-900" style={{ fontWeight: 600 }}>
                  Partner & Request Details
                </h3>
              </div>
              {!editingPartner && (
                <button
                  onClick={() => {
                    setPartnerDraft(partnerData);
                    setEditingPartner(true);
                  }}
                  className="p-1 rounded hover:bg-black/5 text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <Pencil size={12} />
                </button>
              )}
            </div>

            {!partnerConfirmed && !editingPartner && (
              <div className="flex items-start gap-1.5 mb-3 p-2 bg-amber-100 border border-amber-200 rounded-lg">
                <AlertCircle size={13} className="text-amber-600 flex-shrink-0 mt-0.5" />
                <span className="text-xs text-amber-800 leading-snug" style={{ fontWeight: 500 }}>
                  Partner details were not confirmed during review. Please verify before creating the offer.
                </span>
              </div>
            )}

            {editingPartner && partnerDraft ? (
              <div className="space-y-2.5 mt-3">
                {(['partner', 'region', 'requestId', 'contact'] as const).map(key => (
                  <div key={key}>
                    <div className="text-xs text-gray-400 mb-0.5">{summaryPartnerLabel(key)}</div>
                    <input
                      className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] bg-white"
                      value={partnerDraft[key]}
                      onChange={event => setPartnerDraft(draft => draft && { ...draft, [key]: event.target.value })}
                    />
                  </div>
                ))}
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => setEditingPartner(false)}
                    className="flex-1 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-500 hover:bg-gray-50 transition-colors bg-white"
                    style={{ fontWeight: 500 }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      setPartnerData(partnerDraft);
                      setPartnerConfirmed(true);
                      setEditingPartner(false);
                    }}
                    className="flex-1 py-1.5 bg-[#1B4E8A] text-white rounded-lg text-xs hover:bg-[#163d6d] transition-colors"
                    style={{ fontWeight: 600 }}
                  >
                    Save & Confirm
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="space-y-2.5 mt-3">
                  {[
                    { label: 'Organization', value: partnerData.partner },
                    { label: 'Region', value: partnerData.region },
                    { label: 'Request ID', value: partnerData.requestId },
                    { label: 'Contact', value: partnerData.contact },
                    { label: 'Request date', value: partnerData.requestDate ?? 'June 10, 2024' },
                    { label: 'Source file', value: partnerData.sourceFile ?? data.sourceFile },
                  ].map(row => (
                    <div key={row.label}>
                      <div className="text-xs text-gray-400">{row.label}</div>
                      <div className="text-xs text-gray-800" style={{ fontWeight: 500 }}>
                        {row.value}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-3 border-t border-gray-200/60">
                  {partnerConfirmed ? (
                    <div className="flex items-center gap-1.5 text-xs text-green-700" style={{ fontWeight: 500 }}>
                      <CheckCircle2 size={13} /> Details confirmed
                    </div>
                  ) : (
                    <button
                      onClick={() => setPartnerConfirmed(true)}
                      className="w-full py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-xs transition-colors"
                      style={{ fontWeight: 700 }}
                    >
                      Confirm Details
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {offerState !== 'idle' && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
            {offerState === 'generating' ? (
              <div className="p-8 text-center">
                <div className="w-16 h-16 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-5">
                  <Loader2 size={28} className="text-[#1B4E8A] animate-spin" />
                </div>
                <div className="text-gray-900 text-base mb-1.5" style={{ fontWeight: 700 }}>
                  Generating Offer PDF...
                </div>
                <p className="text-gray-500 text-sm leading-relaxed">
                  Compiling {data.items.length} matched items, pricing data, and partner details into
                  a formatted offer document.
                </p>
              </div>
            ) : (
              <div className="p-8">
                <div className="flex items-center justify-between mb-5">
                  <div className="w-14 h-14 rounded-full bg-teal-50 flex items-center justify-center">
                    <CheckCircle2 size={30} className="text-[#0E9E8F]" />
                  </div>
                  <button onClick={() => setOfferState('idle')} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors">
                    <X size={18} />
                  </button>
                </div>
                <div className="text-gray-900 text-lg mb-1" style={{ fontWeight: 700 }}>
                  Offer PDF Ready
                </div>
                <p className="text-gray-500 text-sm mb-1">{offer?.fileName ?? `Offer-${requestId}.pdf`}</p>
                <div className="space-y-1 text-xs text-gray-400 mb-6">
                  <div>
                    {offer?.lineItems ?? data.items.length} line items - EUR{' '}
                    {formatCurrency(offer?.totalValue ?? data.metrics.estimatedTotalValue)}
                  </div>
                  <div>
                    Partner: {offer?.partner ?? partnerData.partner} - Generated: {offer?.generatedAt ?? 'Jun 13, 2024'}
                  </div>
                </div>
                <button
                  className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-[#1B4E8A] text-white rounded-xl hover:bg-[#163d6d] transition-colors shadow-sm mb-2"
                  style={{ fontWeight: 700 }}
                >
                  <FileDown size={16} />
                  Download PDF
                </button>
                <button
                  onClick={() => setOfferState('idle')}
                  className="w-full py-2.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
                  style={{ fontWeight: 500 }}
                >
                  Close
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  sub,
  iconBg,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub: string;
  iconBg: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-gray-500 uppercase tracking-wide" style={{ fontWeight: 600 }}>
          {label}
        </span>
        <div className={`w-9 h-9 rounded-xl ${iconBg} flex items-center justify-center`}>
          {icon}
        </div>
      </div>
      <div className="text-xl text-gray-900" style={{ fontWeight: 700 }}>
        {value}
      </div>
      <div className="text-xs text-gray-400 mt-0.5">{sub}</div>
    </div>
  );
}

function formatCurrency(value: number) {
  return value.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function summaryPartnerLabel(key: keyof Pick<PartnerDetails, 'partner' | 'region' | 'requestId' | 'contact'>) {
  return {
    partner: 'Organization',
    region: 'Region',
    requestId: 'Request ID',
    contact: 'Contact',
  }[key];
}

