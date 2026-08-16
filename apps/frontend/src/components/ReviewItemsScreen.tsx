import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Edit2,
  FileText,
  HelpCircle,
  Info,
  Pencil,
  X,
} from 'lucide-react';
import { getReview, updateItem, updatePartner, verifyItem } from '../api/client';
import type {
  ExtractedItem,
  ItemStatus,
  PartnerDetails,
  Priority,
  ReviewResponse,
  SourceReference,
} from '../api/types';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type ReviewItemsScreenProps = {
  requestId: string;
  initialData?: ReviewResponse | null;
  onContinue: () => void;
};

const PRIORITY_CFG: Record<Priority, { label: string; color: string; bg: string }> = {
  critical: { label: 'Critical', color: 'text-red-700', bg: 'bg-red-100' },
  high: { label: 'High', color: 'text-orange-700', bg: 'bg-orange-100' },
  medium: { label: 'Medium', color: 'text-yellow-700', bg: 'bg-yellow-100' },
  low: { label: 'Low', color: 'text-gray-600', bg: 'bg-gray-100' },
};

const STATUS_CFG: Record<
  ItemStatus,
  { label: string; icon: ReactNode; color: string; bg: string }
> = {
  verified: {
    label: 'Verified',
    icon: <CheckCircle2 size={11} />,
    color: 'text-green-700',
    bg: 'bg-green-100',
  },
  needs_review: {
    label: 'Needs Verification',
    icon: <AlertCircle size={11} />,
    color: 'text-amber-700',
    bg: 'bg-amber-100',
  },
  low_confidence: {
    label: 'Low Confidence',
    icon: <AlertTriangle size={11} />,
    color: 'text-red-700',
    bg: 'bg-red-100',
  },
  missing: {
    label: 'Missing',
    icon: <HelpCircle size={11} />,
    color: 'text-red-700',
    bg: 'bg-red-100',
  },
};

function needsManualReview(item: ExtractedItem) {
  return item.status === 'low_confidence' || item.status === 'missing';
}

export function ReviewItemsScreen({ requestId, initialData, onContinue }: ReviewItemsScreenProps) {
  const [data, setData] = useState<ReviewResponse | null>(initialData ?? null);
  const [items, setItems] = useState<ExtractedItem[]>(initialData?.items ?? []);
  const [partnerDetails, setPartnerDetails] = useState<PartnerDetails | null>(
    initialData?.partner ?? null,
  );
  const [editingItem, setEditingItem] = useState<ExtractedItem | null>(null);
  const [editValues, setEditValues] = useState<Partial<ExtractedItem>>({});
  const [editingPartner, setEditingPartner] = useState(false);
  const [partnerDraft, setPartnerDraft] = useState<PartnerDetails | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(!initialData);

  useEffect(() => {
    if (initialData) {
      setData(initialData);
      setItems(initialData.items);
      setPartnerDetails(initialData.partner);
      setIsLoading(false);
      return;
    }

    let mounted = true;
    setIsLoading(true);
    getReview(requestId)
      .then(response => {
        if (mounted) {
          setData(response);
          setItems(response.items);
          setPartnerDetails(response.partner);
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
  }, [initialData, requestId]);

  const sourceReferences = useMemo(
    () =>
      Object.fromEntries(
        (data?.sourceReferences ?? []).map(reference => [reference.itemId, reference]),
      ) as Record<number, SourceReference>,
    [data],
  );

  const verified = items.filter(item => item.status === 'verified').length;
  const needsReview = items.filter(item => item.status === 'needs_review').length;
  const lowConfidence = items.filter(item => item.status === 'low_confidence').length;
  const missing = items.filter(item => item.status === 'missing').length;
  const allVerified = items.length > 0 && verified === items.length;
  const blockedItems = items.filter(needsManualReview);

  const openEdit = (item: ExtractedItem) => {
    setEditingItem(item);
    setEditValues({
      name: item.name,
      quantity: item.quantity,
      unit: item.unit,
      notes: item.notes,
      priority: item.priority,
    });
  };

  const saveEdit = async () => {
    if (!editingItem) {
      return;
    }

    try {
      const updated = await updateItem(requestId, editingItem.id, {
        name: editValues.name,
        quantity: editValues.quantity,
        unit: editValues.unit,
        notes: editValues.notes,
        priority: editValues.priority,
      });
      setItems(prev => prev.map(item => (item.id === updated.id ? updated : item)));
      setEditingItem(null);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to save item');
    }
  };

  const markVerified = async (id: number) => {
    try {
      const updated = await verifyItem(requestId, id);
      setItems(prev => prev.map(item => (item.id === id ? updated : item)));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to verify item');
    }
  };

  const startEditPartner = () => {
    if (partnerDetails) {
      setPartnerDraft({ ...partnerDetails });
      setEditingPartner(true);
    }
  };

  const savePartner = async () => {
    if (!partnerDraft) {
      return;
    }

    try {
      const updated = await updatePartner(requestId, {
        partner: partnerDraft.partner,
        region: partnerDraft.region,
        requestId: partnerDraft.requestId,
        contact: partnerDraft.contact,
      });
      setPartnerDetails({
        ...partnerDraft,
        ...updated,
        requestDate: partnerDetails?.requestDate,
        sourceFile: partnerDetails?.sourceFile,
      });
      setEditingPartner(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to save partner details');
    }
  };

  if (isLoading) {
    return (
      <div className="p-6">
        <LoadingPanel label="Loading extracted items" />
      </div>
    );
  }

  if (!data || !partnerDetails) {
    return (
      <div className="p-6">
        <ErrorPanel message={error ?? 'Review data is unavailable'} />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-6">
        <WorkflowStepper currentStep="review" />
      </div>

      {error && <div className="mb-4"><ErrorPanel message={error} /></div>}

      <div className="flex gap-5 items-start">
        <div className="flex-1 min-w-0">
          <div className="mb-4">
            <h1 className="text-gray-900">Review Extracted Items</h1>
            <p className="text-gray-500 text-sm mt-0.5">
              Verify that all extracted items are correct. Click any item name or action button to
              open the source reference and make corrections.
            </p>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2.5 flex items-center gap-2 mb-3">
            <FileText size={14} className="text-blue-500 flex-shrink-0" />
            <span className="text-sm text-blue-700">
              Source: <span style={{ fontWeight: 500 }}>{data.source.fileName}</span>
            </span>
            <span className="text-blue-300 mx-1">-</span>
            <span className="text-sm text-blue-600">
              {data.source.rowsDetected} rows detected - Partner: {data.source.partner}
            </span>
          </div>

          {blockedItems.length > 0 && (
            <div className="bg-amber-50 border border-amber-300 rounded-lg px-4 py-3 flex items-start gap-2.5 mb-4">
              <AlertTriangle size={15} className="text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-sm text-amber-800" style={{ fontWeight: 700 }}>
                  {blockedItems.length} item(s) require manual review before you can proceed
                </div>
                <div className="text-xs text-amber-700 mt-0.5 leading-relaxed">
                  Click the item name or Review Required to open the source reference and fill in
                  the correct values.
                </div>
              </div>
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50/80">
                  {['#', 'Item Name', 'Qty', 'Unit', 'Notes', 'Priority', 'Confidence', 'Status', 'Actions'].map(header => (
                    <th
                      key={header}
                      className="text-left px-4 py-3 text-xs text-gray-500"
                      style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => {
                  const status = STATUS_CFG[item.status];
                  const priority = PRIORITY_CFG[item.priority];
                  const blocked = needsManualReview(item);
                  const missingName = item.status === 'missing' || !item.name;

                  return (
                    <tr
                      key={item.id}
                      className={`border-b border-gray-100 transition-colors ${
                        blocked
                          ? 'bg-amber-50 hover:bg-amber-100/60'
                          : item.status === 'needs_review'
                            ? 'bg-amber-50/30 hover:bg-amber-50/60'
                            : 'hover:bg-gray-50/60'
                      }`}
                      style={blocked ? { boxShadow: 'inset 3px 0 0 #F59E0B' } : undefined}
                    >
                      <td className="px-4 py-3 text-xs text-gray-400">{index + 1}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => openEdit(item)}
                          className={`text-left transition-colors hover:underline ${
                            missingName ? 'text-gray-400 italic' : 'text-gray-900 hover:text-[#1B4E8A]'
                          }`}
                          style={{ fontWeight: missingName ? 400 : 500, fontSize: 14 }}
                        >
                          {missingName ? '- Missing -' : item.name}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        {item.quantity !== null ? (
                          <span className="text-sm text-gray-900" style={{ fontWeight: 500 }}>
                            {item.quantity.toLocaleString()}
                          </span>
                        ) : (
                          <span className="text-sm text-gray-400 italic">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {item.unit ? (
                          <span className="text-sm text-gray-500">{item.unit}</span>
                        ) : (
                          <span className="text-sm text-gray-400 italic">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-xs">
                        <span className={`text-xs ${item.notes ? 'text-gray-500' : 'text-gray-300 italic'}`}>
                          {item.notes || '-'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-xs ${priority.bg} ${priority.color}`} style={{ fontWeight: 600 }}>
                          {priority.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {item.confidence === null ? (
                          <span className="text-xs text-gray-400 italic">N/A</span>
                        ) : (
                          <div className="flex items-center gap-2">
                            <div className="w-14 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  item.confidence >= 85
                                    ? 'bg-green-500'
                                    : item.confidence >= 70
                                      ? 'bg-amber-500'
                                      : 'bg-red-500'
                                }`}
                                style={{ width: `${item.confidence}%` }}
                              />
                            </div>
                            <span
                              className={`text-xs ${
                                item.confidence >= 85
                                  ? 'text-green-700'
                                  : item.confidence >= 70
                                    ? 'text-amber-700'
                                    : 'text-red-700'
                              }`}
                              style={{ fontWeight: 600 }}
                            >
                              {item.confidence}%
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${status.bg} ${status.color}`} style={{ fontWeight: 500 }}>
                          {status.icon} {status.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {blocked ? (
                            <button
                              onClick={() => openEdit(item)}
                              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-amber-500 text-white hover:bg-amber-600 transition-colors shadow-sm"
                              style={{ fontWeight: 700 }}
                            >
                              <AlertTriangle size={12} />
                              Review Required
                            </button>
                          ) : (
                            <>
                              <button
                                onClick={() => openEdit(item)}
                                className="flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
                                style={{ fontWeight: 500 }}
                              >
                                <Edit2 size={11} /> Edit
                              </button>
                              {item.status === 'needs_review' && (
                                <button
                                  onClick={() => void markVerified(item.id)}
                                  className="px-2 py-1 rounded-md text-xs bg-green-100 text-green-700 hover:bg-green-200 transition-colors"
                                  style={{ fontWeight: 600 }}
                                >
                                  Verify
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-5 flex items-center justify-between gap-4">
            <div className="text-xs leading-relaxed">
              {blockedItems.length > 0 ? (
                <span className="text-amber-700" style={{ fontWeight: 500 }}>
                  <AlertTriangle size={12} className="inline mr-1 mb-0.5" />
                  {blockedItems.map(item => item.name || '(missing item)').join(', ')} must be reviewed before proceeding.
                </span>
              ) : needsReview > 0 ? (
                <span className="text-amber-600">
                  {needsReview} item(s) still flagged for review. Click Verify or Edit to confirm them.
                </span>
              ) : (
                <span className="text-green-700" style={{ fontWeight: 500 }}>
                  All items verified. Ready to proceed.
                </span>
              )}
            </div>
            <button
              onClick={() => setShowConfirmDialog(true)}
              disabled={!allVerified}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm transition-all flex-shrink-0 ${
                allVerified
                  ? 'bg-[#1B4E8A] text-white hover:bg-[#163d6d] shadow-sm cursor-pointer'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed'
              }`}
              style={{ fontWeight: 500 }}
            >
              Confirm Items & Start Matching
              <ArrowRight size={15} />
            </button>
          </div>
        </div>

        <div className="w-56 flex-shrink-0 sticky top-6 space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-gray-900 text-sm mb-4" style={{ fontWeight: 600 }}>
              Extraction Summary
            </h3>
            <SummaryRow label="Total rows" value={items.length} />
            <SummaryRow label="Verified" value={verified} icon={<CheckCircle2 size={13} className="text-green-500" />} tone="green" />
            <SummaryRow label="Needs Verification" value={needsReview} icon={<AlertCircle size={13} className="text-amber-500" />} tone="amber" />
            <SummaryRow label="Low Confidence" value={lowConfidence} icon={<AlertTriangle size={13} className="text-red-500" />} tone="red" />
            <SummaryRow label="Missing" value={missing} icon={<HelpCircle size={13} className="text-red-500" />} tone="red" last />
            <div className="mt-4 pt-3 border-t border-gray-100">
              <div className="flex justify-between text-xs text-gray-400 mb-1.5">
                <span>Verification</span>
                <span>{items.length ? Math.round((verified / items.length) * 100) : 0}%</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500 rounded-full transition-all"
                  style={{ width: `${items.length ? (verified / items.length) * 100 : 0}%` }}
                />
              </div>
            </div>
          </div>

          <div className={`bg-white rounded-xl border p-5 ${partnerDetails.confirmed ? 'border-green-200' : 'border-gray-200'}`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-gray-900 text-sm" style={{ fontWeight: 600 }}>
                Request Details
              </h3>
              <div className="flex items-center gap-1.5">
                {partnerDetails.confirmed && !editingPartner && <CheckCircle2 size={14} className="text-green-500" />}
                {!editingPartner && (
                  <button
                    onClick={startEditPartner}
                    className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                    title="Edit partner details"
                  >
                    <Pencil size={12} />
                  </button>
                )}
              </div>
            </div>

            {editingPartner && partnerDraft ? (
              <div className="space-y-2.5">
                {(['partner', 'region', 'requestId', 'contact'] as const).map(key => (
                  <div key={key}>
                    <div className="text-xs text-gray-400 mb-0.5">{partnerLabel(key)}</div>
                    <input
                      className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      value={partnerDraft[key]}
                      onChange={event => setPartnerDraft(draft => draft && { ...draft, [key]: event.target.value })}
                    />
                  </div>
                ))}
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => setEditingPartner(false)}
                    className="flex-1 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-500 hover:bg-gray-50 transition-colors"
                    style={{ fontWeight: 500 }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => void savePartner()}
                    className="flex-1 py-1.5 bg-[#1B4E8A] text-white rounded-lg text-xs hover:bg-[#163d6d] transition-colors"
                    style={{ fontWeight: 600 }}
                  >
                    Save & Confirm
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="space-y-2.5 mb-4">
                  {[
                    { label: 'Partner', value: partnerDetails.partner },
                    { label: 'Region', value: partnerDetails.region },
                    { label: 'Request ID', value: partnerDetails.requestId },
                    { label: 'Contact', value: partnerDetails.contact },
                  ].map(row => (
                    <div key={row.label}>
                      <div className="text-xs text-gray-400">{row.label}</div>
                      <div className="text-xs text-gray-800" style={{ fontWeight: 500 }}>
                        {row.value}
                      </div>
                    </div>
                  ))}
                </div>
                {!partnerDetails.confirmed ? (
                  <button
                    onClick={() => setPartnerDetails(details => details && { ...details, confirmed: true })}
                    className="w-full py-1.5 bg-[#1B4E8A] text-white rounded-lg text-xs hover:bg-[#163d6d] transition-colors"
                    style={{ fontWeight: 600 }}
                  >
                    Confirm Details
                  </button>
                ) : (
                  <div className="flex items-center gap-1.5 text-xs text-green-700" style={{ fontWeight: 500 }}>
                    <CheckCircle2 size={12} /> Details confirmed
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {editingItem && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">
            <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-gray-900">
                  {editingItem.status === 'missing' ? 'Complete Missing Information' : 'Edit Extracted Item'}
                </h3>
                <p className="text-gray-500 text-sm mt-0.5">Row #{editingItem.id} in source document</p>
              </div>
              <button onClick={() => setEditingItem(null)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors">
                <X size={18} />
              </button>
            </div>

            <div className="px-6 py-5">
              <SourceReferencePanel item={editingItem} reference={sourceReferences[editingItem.id]} />
              <div className="space-y-4">
                <div>
                  <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                    Item Name
                  </label>
                  <input
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                    value={editValues.name ?? ''}
                    onChange={event => setEditValues(values => ({ ...values, name: event.target.value }))}
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                      Quantity
                    </label>
                    <input
                      type="number"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      value={editValues.quantity ?? ''}
                      onChange={event =>
                        setEditValues(values => ({
                          ...values,
                          quantity: event.target.value ? Number(event.target.value) : null,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                      Unit
                    </label>
                    <input
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      value={editValues.unit ?? ''}
                      onChange={event => setEditValues(values => ({ ...values, unit: event.target.value }))}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                    Notes / Specification
                  </label>
                  <input
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                    value={editValues.notes ?? ''}
                    onChange={event => setEditValues(values => ({ ...values, notes: event.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                    Priority
                  </label>
                  <select
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] bg-white"
                    value={editValues.priority ?? editingItem.priority}
                    onChange={event =>
                      setEditValues(values => ({ ...values, priority: event.target.value as Priority }))
                    }
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => setEditingItem(null)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                style={{ fontWeight: 500 }}
              >
                Cancel
              </button>
              <button
                onClick={() => void saveEdit()}
                className="px-5 py-2 bg-[#1B4E8A] text-white rounded-lg text-sm hover:bg-[#163d6d] transition-colors"
                style={{ fontWeight: 600 }}
              >
                Save & Mark Verified
              </button>
            </div>
          </div>
        </div>
      )}

      {showConfirmDialog && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
            <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mb-4">
              <AlertTriangle size={22} className="text-amber-600" />
            </div>
            <h3 className="text-gray-900 mb-2">Proceed to Smart Matching?</h3>
            <p className="text-gray-500 text-sm leading-relaxed">
              Once you proceed, the extracted item list will be locked. The matching step requires
              significant compute and cannot be undone without starting a new request.
            </p>
            <div className="mt-5 bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div className="text-xs text-gray-500" style={{ fontWeight: 600 }}>
                Summary
              </div>
              <div className="text-xs text-gray-700 mt-1">
                {items.length} items - {verified} verified - Partner: {partnerDetails.partner}
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setShowConfirmDialog(false)}
                className="px-4 py-2.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                style={{ fontWeight: 500 }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowConfirmDialog(false);
                  onContinue();
                }}
                className="px-6 py-2.5 bg-[#1B4E8A] text-white rounded-lg text-sm hover:bg-[#163d6d] transition-colors"
                style={{ fontWeight: 600 }}
              >
                Yes, start matching
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryRow({
  label,
  value,
  icon,
  tone,
  last,
}: {
  label: string;
  value: number;
  icon?: ReactNode;
  tone?: 'green' | 'amber' | 'red';
  last?: boolean;
}) {
  const color =
    tone === 'green' ? 'text-green-700' : tone === 'amber' ? 'text-amber-700' : tone === 'red' ? 'text-red-700' : 'text-gray-900';

  return (
    <div className={`flex justify-between items-center py-1.5 ${last ? '' : 'border-b border-gray-100'}`}>
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-sm text-gray-500">{label}</span>
      </div>
      <span className={`text-sm ${color}`} style={{ fontWeight: 700 }}>
        {value}
      </span>
    </div>
  );
}

function SourceReferencePanel({
  item,
  reference,
}: {
  item: ExtractedItem;
  reference?: SourceReference;
}) {
  const isMissing = item.status === 'missing';

  return (
    <div className={`border rounded-xl p-4 mb-5 ${isMissing ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'}`}>
      <div className="flex items-center gap-2 mb-2">
        <BookOpen size={14} className={isMissing ? 'text-red-500' : 'text-amber-600'} />
        <span className={`text-xs ${isMissing ? 'text-red-800' : 'text-amber-800'}`} style={{ fontWeight: 700 }}>
          Source Reference - Page {reference?.page ?? '-'}, Row {reference?.row ?? '-'}
        </span>
      </div>
      <div
        className={`mt-1.5 rounded-lg px-3 py-2 text-xs font-mono leading-relaxed italic ${
          isMissing ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'
        }`}
      >
        {reference?.excerpt ?? 'No source reference available'}
      </div>
      <div className={`flex items-center gap-1.5 mt-2 text-xs ${isMissing ? 'text-red-600' : 'text-amber-600'}`}>
        <Info size={11} />
        {isMissing
          ? 'Item name extracted. Quantity could not be read. Please enter it manually.'
          : `Extracted with ${item.confidence}% confidence`}
      </div>
    </div>
  );
}

function partnerLabel(key: keyof Pick<PartnerDetails, 'partner' | 'region' | 'requestId' | 'contact'>) {
  return {
    partner: 'Partner',
    region: 'Region',
    requestId: 'Request ID',
    contact: 'Contact',
  }[key];
}

