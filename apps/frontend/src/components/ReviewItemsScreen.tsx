import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  Loader2,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Edit2,
  FileText,
  HelpCircle,
  Info,
  ChevronDown,
  ChevronRight,
  ListPlus,
  Pencil,
  PenLine,
  Plus,
  X,
} from 'lucide-react';
import {
  addCustomColumn,
  addManualItem,
  confirmPartner,
  getReview,
  removeManualItem,
  reviewWithAi,
  updateColumnLabel,
  updateItem,
  updatePartner,
  verifyItem,
} from '../api/client';
import type {
  ExtractedItem,
  ItemStatus,
  ManualItemCreate,
  PartnerDetails,
  Priority,
  ReviewResponse,
  SourceReference,
} from '../api/types';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type ReviewItemsScreenProps = {
  requestId: string | null;
  initialData?: ReviewResponse | null;
  onContinue: () => void;
  onCreateManual?: (
    item: ManualItemCreate, partner: PartnerDetails, columnLabels: Record<string, string>,
  ) => Promise<ReviewResponse>;
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
  return item.status === 'low_confidence' || item.status === 'missing' || !item.domain || !!item.reviewReasons?.length;
}

/** A column header or attribute label that renames itself in place - click to edit, Enter/blur
 * saves, Escape cancels. Used for both <th> core-column headers and <dt> attribute labels, since
 * both are just "this column's display name" from the rename endpoint's point of view. */
function EditableLabel({ value, onSave }: { value: string; onSave: (next: string) => void }) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);

  if (isEditing) {
    const commit = () => {
      setIsEditing(false);
      const trimmed = draft.trim();
      if (trimmed && trimmed !== value) {
        onSave(trimmed);
      } else {
        setDraft(value);
      }
    };

    return (
      <input
        autoFocus
        value={draft}
        onFocus={event => event.target.select()}
        onChange={event => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={event => {
          if (event.key === 'Enter') {
            event.currentTarget.blur();
          } else if (event.key === 'Escape') {
            setDraft(value);
            setIsEditing(false);
          }
        }}
        onClick={event => event.stopPropagation()}
        className="border border-[#1B4E8A] rounded px-1 py-0.5 outline-none bg-white"
        style={{ font: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit', width: '9rem' }}
      />
    );
  }

  return (
    <button
      onClick={() => setIsEditing(true)}
      className="group inline-flex items-center gap-1 hover:text-[#1B4E8A] transition-colors"
      title="Click to rename this column"
      type="button"
    >
      <span>{value}</span>
      <Pencil size={10} className="opacity-0 group-hover:opacity-60 transition-opacity flex-shrink-0" />
    </button>
  );
}

export function ReviewItemsScreen({ requestId, initialData, onContinue, onCreateManual }: ReviewItemsScreenProps) {
  const [data, setData] = useState<ReviewResponse | null>(initialData ?? null);
  const [items, setItems] = useState<ExtractedItem[]>(initialData?.items ?? []);
  const [partnerDetails, setPartnerDetails] = useState<PartnerDetails | null>(
    initialData?.partner ?? null,
  );
  const [editingItem, setEditingItem] = useState<ExtractedItem | null>(null);
  const [isNewItem, setIsNewItem] = useState(false);
  const [isSavingItem, setIsSavingItem] = useState(false);
  const [removingItemId, setRemovingItemId] = useState<number | null>(null);
  const [itemError, setItemError] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Partial<ExtractedItem>>({});
  const unitInferred = Boolean(editingItem?.inferredFields?.unit) && editValues.unit === editingItem?.unit;
  const typeInferred = Boolean(editingItem?.inferredFields?.type) && editValues.domain === editingItem?.domain;
  useEffect(() => {
    if (!editingItem) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSavingItem) {
        event.preventDefault();
        setEditingItem(null);
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [editingItem, isSavingItem]);
  const [editingPartner, setEditingPartner] = useState(false);
  const [partnerDraft, setPartnerDraft] = useState<PartnerDetails | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(!initialData);
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  const [columnLabels, setColumnLabels] = useState<Record<string, string>>(
    initialData?.columnLabels ?? {},
  );
  const [availableColumns, setAvailableColumns] = useState<string[]>(
    initialData?.availableColumns ?? [],
  );
  const [newColumnName, setNewColumnName] = useState('');
  const [isAddingColumn, setIsAddingColumn] = useState(false);
  const [isReviewingAi, setIsReviewingAi] = useState(false);
  const busyDialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isReviewingAi) return;
    const appRoot = document.getElementById('root');
    const alreadyInert = appRoot?.hasAttribute('inert');
    const previousFocus = document.activeElement;
    appRoot?.setAttribute('inert', '');
    busyDialog.current?.focus();
    return () => {
      if (!alreadyInert) appRoot?.removeAttribute('inert');
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [isReviewingAi]);
  const runAiReview = async () => {
    if (!requestId || isReviewingAi) return;
    setIsReviewingAi(true);
    setError(null);
    try {
      const reviewed = await reviewWithAi(requestId);
      setData(reviewed);
      setItems(reviewed.items);
      setPartnerDetails(reviewed.partner);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to review with AI');
    } finally { setIsReviewingAi(false); }
  };

  // key is a core-field key ('name', 'quantity', ...) or an attribute column's own label - see
  // ReviewResponse.columnLabels. Optimistic: applies locally first so the header doesn't flicker
  // back to its old text while the request is in flight, then reconciles with the server's copy.
  const renameColumn = (key: string, label: string) => {
    setColumnLabels(previous => ({ ...previous, [key]: label }));
    if (!requestId) return;
    updateColumnLabel(requestId, key, label)
      .then(setColumnLabels)
      .catch(caught => {
        setError(caught instanceof Error ? caught.message : 'Unable to rename column');
      });
  };

  const columnLabel = (key: string, fallback: string) => columnLabels[key] ?? fallback;

  const existingColumnLabels = useMemo(
    () => new Set((data?.attributeColumns ?? []).map(label => label.toLowerCase())),
    [data],
  );

  // Passes the same string as both displayName and hint: it's either picked verbatim from
  // availableColumns (an exact detected header, so the deterministic hint match resolves it for
  // free) or typed freely by the user, in which case it still guides the LLM fallback match the
  // same way a hint would - see CustomColumnRequest / app.parsing.custom_columns.
  const submitNewColumn = async () => {
    if (!requestId) return;
    const trimmed = newColumnName.trim();
    if (!trimmed || isAddingColumn || isSavingItem || removingItemId !== null || existingColumnLabels.has(trimmed.toLowerCase())) {
      return;
    }

    setIsAddingColumn(true);
    try {
      const response = await addCustomColumn(requestId, { displayName: trimmed, hint: trimmed });
      setData(response);
      setItems(response.items);
      setColumnLabels(response.columnLabels ?? {});
      setAvailableColumns(response.availableColumns ?? []);
      setNewColumnName('');
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to add column');
    } finally {
      setIsAddingColumn(false);
    }
  };

  const toggleExpanded = (itemId: number) =>
    setExpandedItems(previous => {
      const next = new Set(previous);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });

  useEffect(() => {
    if (initialData) {
      setData(initialData);
      setItems(initialData.items);
      setPartnerDetails(initialData.partner);
      if (!initialData.source.fileName && !initialData.partner.confirmed) {
        setPartnerDraft(initialData.partner);
        setEditingPartner(true);
      }
      setColumnLabels(initialData.columnLabels ?? {});
      setAvailableColumns(initialData.availableColumns ?? []);
      setIsLoading(false);
      return;
    }

    let mounted = true;
    if (!requestId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    getReview(requestId)
      .then(response => {
        if (mounted) {
          setData(response);
          setItems(response.items);
          setPartnerDetails(response.partner);
          if (!response.source.fileName && !response.partner.confirmed) {
            setPartnerDraft(response.partner);
            setEditingPartner(true);
          }
          setColumnLabels(response.columnLabels ?? {});
          setAvailableColumns(response.availableColumns ?? []);
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

  // Columns vary per uploaded file - a bare name/qty/unit sheet contributes none, while a full
  // RFQ form contributes several. Fall back to whatever the items carry if the server didn't
  // send an explicit ordering.
  const attributeColumns =
    data?.attributeColumns && data.attributeColumns.length > 0
      ? data.attributeColumns
      : Array.from(new Set(items.flatMap(item => Object.keys(item.attributes ?? {}))));

  // Optional core columns only earn their width when the file populated them - the same
  // adaptive rule the extra columns follow, so a sparse request form stays readable.
  const showItemNumber = items.some(item => item.itemNumber);
  const showUnit = items.some(item => item.unit);
  const showShelfLife = items.some(item => item.shelfLife);
  const showNotes = items.some(item => item.notes);
  const columnCount =
    8 +
    (attributeColumns.length > 0 ? 1 : 0) +
    [showItemNumber, showUnit, showShelfLife, showNotes].filter(Boolean).length;

  const verified = items.filter(item => item.status === 'verified').length;
  const needsReview = items.filter(item => item.status === 'needs_review').length;
  const lowConfidence = items.filter(item => item.status === 'low_confidence').length;
  const missing = items.filter(item => item.status === 'missing').length;
  const manualCount = items.filter(item => item.manual).length;
  const isManualRequest = !!data && !data.source.fileName;
  const itemMutationPending = isReviewingAi || isSavingItem || removingItemId !== null;
  const allVerified = items.length > 0 && verified === items.length && items.every(item => item.domain && !item.reviewReasons?.length)
    && !itemMutationPending && !isAddingColumn;
  const blockedItems = items.filter(needsManualReview);

  const openEdit = (item: ExtractedItem) => {
    if (isReviewingAi) return;
    setIsNewItem(false);
    setItemError(null);
    setEditingItem(item);
    setEditValues({
      name: item.name,
      quantity: item.quantity,
      unit: item.unit,
      notes: item.notes,
      itemNumber: item.itemNumber,
      shelfLife: item.shelfLife,
      priority: item.priority,
      domain: item.domain,
    });
  };

  const openAdd = () => {
    const item: ExtractedItem = {
      id: 0, name: '', quantity: null, unit: '', notes: '', itemNumber: '', shelfLife: '',
      attributes: {}, priority: 'medium', confidence: null, status: 'verified',
      domain: null, manual: true,
    };
    openEdit(item);
    setIsNewItem(true);
  };

  const canSave = !!editValues.name?.trim() && Number.isInteger(editValues.quantity)
    && (editValues.quantity ?? 0) > 0 && !!editValues.domain;

  const saveEdit = async () => {
    if (!editingItem || isSavingItem || !canSave) {
      return;
    }

    setIsSavingItem(true);
    setItemError(null);
    try {
      const payload = {
        name: editValues.name!.trim(),
        quantity: editValues.quantity!,
        unit: editValues.unit ?? '',
        notes: editValues.notes ?? '',
        itemNumber: editValues.itemNumber ?? '',
        shelfLife: editValues.shelfLife ?? '',
        priority: editValues.priority ?? 'medium',
        domain: editValues.domain!,
      };
      if (!requestId) {
        if (!isNewItem || !onCreateManual || !partnerDetails) return;
        await onCreateManual(
          payload, editingPartner && partnerDraft ? partnerDraft : partnerDetails, columnLabels,
        );
        setEditingItem(null);
        return;
      }
      const updated = isNewItem
        ? await addManualItem(requestId, payload)
        : await updateItem(requestId, editingItem.id, payload);
      setItems(prev => isNewItem ? [...prev, updated] : prev.map(item => (item.id === updated.id ? updated : item)));
      setEditingItem(null);
      setError(null);
    } catch (caught) {
      setItemError(caught instanceof Error ? caught.message : 'Unable to save item');
    } finally {
      setIsSavingItem(false);
    }
  };

  const removeItem = async (id: number) => {
    if (!requestId || itemMutationPending) return;
    setRemovingItemId(id);
    try {
      await removeManualItem(requestId, id);
      setItems(previous => previous.filter(item => item.id !== id));
      setExpandedItems(previous => {
        const next = new Set(previous);
        next.delete(id);
        return next;
      });
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to remove item');
    } finally {
      setRemovingItemId(null);
    }
  };

  const markVerified = async (id: number) => {
    if (!requestId) return;
    const item = items.find(value => value.id === id);
    if (item && !item.domain) {
      openEdit(item);
      return;
    }
    try {
      const updated = await verifyItem(requestId, id);
      setItems(prev => prev.map(item => (item.id === id ? updated : item)));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to verify item');
    }
  };

  const startEditPartner = () => {
    if (partnerDetails && !partnerDetails.confirmed) {
      setPartnerDraft({ ...partnerDetails });
      setEditingPartner(true);
    }
  };

  const savePartner = async () => {
    if (!partnerDraft) {
      return;
    }

    try {
      const updated = requestId ? await updatePartner(requestId, {
        partner: partnerDraft.partner,
        region: partnerDraft.region,
        requestId: partnerDraft.requestId,
        contact: partnerDraft.contact,
      }) : partnerDraft;
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

  const confirmPartnerDetails = async () => {
    try {
      const updated = requestId ? await confirmPartner(requestId) : { confirmed: true };
      setPartnerDetails(details => details && { ...details, ...updated });
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to confirm partner details');
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
    <div className="p-6" aria-busy={isReviewingAi}>
      {isReviewingAi && createPortal(
        <div className="fixed inset-0 z-[100] bg-black/40 flex items-center justify-center p-6">
          <div ref={busyDialog} role="dialog" aria-modal="true" aria-labelledby="ai-review-loading" tabIndex={-1}
            onKeyDown={event => { if (event.key === 'Tab') event.preventDefault(); }}
            className="rounded-2xl bg-white p-8 shadow-xl text-center outline-none">
            <Loader2 size={32} className="animate-spin text-[#1B4E8A] mx-auto mb-4" aria-hidden="true" />
            <h2 id="ai-review-loading" className="text-gray-900">Checking items with AI</h2>
            <p className="text-sm text-gray-500 mt-2" role="status">Please wait while the copied values are checked.</p>
          </div>
        </div>, document.body,
      )}
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-6">
        <WorkflowStepper currentStep="review" />
      </div>

      {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
      {!!data.parserWarnings?.some(warning => !warning.startsWith('Ignored supplier/admin columns:')) && (
        <div role="status" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-semibold">Import notes — check the source before continuing</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {data.parserWarnings.filter(warning => !warning.startsWith('Ignored supplier/admin columns:')).map((warning, index) => <li key={index}>{warning}</li>)}
          </ul>
        </div>
      )}

      {!!data.parserWarnings?.some(warning => warning.startsWith('Ignored supplier/admin columns:')) && <details className="mb-4 text-sm text-gray-500">
        <summary className="cursor-pointer">Source column notes</summary>
        {data.parserWarnings.filter(warning => warning.startsWith('Ignored supplier/admin columns:')).map((warning, index) => <p key={index} className="mt-2">{warning}</p>)}
      </details>}
      {!isManualRequest && <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 flex items-center justify-between gap-4">
        <div className="text-sm text-gray-700" role="status">
          {data.reviewSummary?.status ? <>
            <p>{data.reviewSummary.checked ?? 0} rows AI checked · {data.reviewSummary.corrected ?? 0} corrected · {items.filter(item => !item.manual && (item.status !== 'verified' || item.reviewReasons?.length)).length} unresolved</p>
            {data.reviewSummary.message && <p className="text-amber-700 mt-1">{data.reviewSummary.message}</p>}
          </> : <p>AI can check copied values and fill clear types and units.</p>}
        </div>
        {data.reviewSummary?.status !== 'completed' && <button type="button" onClick={() => void runAiReview()} disabled={!requestId || isReviewingAi || isAddingColumn || itemMutationPending || !!editingItem}
          className="px-3 py-2 text-sm rounded-lg bg-[#1B4E8A] text-white disabled:opacity-50 flex-shrink-0">
          {isReviewingAi ? 'Reviewing with AI…' : 'Review with AI'}
        </button>}
      </div>}

      <div className="flex flex-col xl:flex-row gap-5 items-start">
        <div className="w-full flex-1 min-w-0">
          <div className="mb-4">
            <h1 className="text-gray-900">{isManualRequest ? 'Build Manual Request' : 'Review Extracted Items'}</h1>
            <p className="text-gray-500 text-sm mt-0.5">
              {isManualRequest
                ? 'Add each requested item with a quantity and product type. Manually entered items are treated as verified.'
                : 'Check the extracted items and suggested product types. Edit a type if it is wrong or still unclear. Missed a row? Add it manually below the table.'}
            </p>
          </div>

          {isManualRequest ? (
            <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 flex items-center gap-2 mb-3">
              <PenLine size={14} className="text-slate-500 flex-shrink-0" />
              <span className="text-sm text-slate-700">Source: <span className="font-medium">Manual entry</span></span>
              <span className="text-slate-300 mx-1">·</span>
              <span className="text-sm text-slate-600">{items.length} item(s) added</span>
            </div>
          ) : (
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2.5 flex items-center gap-2 mb-3">
            <FileText size={14} className="text-blue-500 flex-shrink-0" />
            <span className="text-sm text-blue-700">
              Source: <span style={{ fontWeight: 500 }}>{data.source.fileName}</span>
            </span>
            <span className="text-blue-300 mx-1">-</span>
            <span className="text-sm text-blue-600">
              {data.source.rowsDetected} rows detected{manualCount > 0 && ` · ${manualCount} added manually`} · Partner: {partnerDetails.partner || '—'}
            </span>
          </div>
          )}

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

          {!isManualRequest && <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 mb-3 flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 text-gray-500 flex-shrink-0">
              <ListPlus size={14} />
              <span className="text-xs" style={{ fontWeight: 600 }}>
                Add column
              </span>
            </div>
            <input
              type="text"
              list="available-columns-suggestions"
              placeholder={
                availableColumns.length > 0
                  ? 'Pick a detected column or type your own...'
                  : 'Type a column name (e.g. Batch Number)...'
              }
              value={newColumnName}
              onChange={event => setNewColumnName(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') {
                  void submitNewColumn();
                }
              }}
              disabled={isAddingColumn || isReviewingAi || itemMutationPending}
              className="flex-1 min-w-[200px] border border-gray-300 rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] disabled:bg-gray-50"
            />
            <datalist id="available-columns-suggestions">
              {availableColumns.map(column => (
                <option key={column} value={column} />
              ))}
            </datalist>
            <button
              onClick={() => void submitNewColumn()}
              disabled={!newColumnName.trim() || isAddingColumn || isReviewingAi || itemMutationPending}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs flex-shrink-0 transition-colors ${
                newColumnName.trim() && !isAddingColumn
                  ? 'bg-[#1B4E8A] text-white hover:bg-[#163d6d]'
                  : 'bg-gray-100 text-gray-400 cursor-not-allowed'
              }`}
              style={{ fontWeight: 600 }}
            >
              <Plus size={12} /> {isAddingColumn ? 'Adding...' : 'Add'}
            </button>
          </div>}

          <div role="region" aria-label="Request items table" tabIndex={0} className="bg-white rounded-xl border border-gray-200 max-w-full max-h-[min(65vh,42rem)] overflow-auto overscroll-contain focus-visible:outline-2 focus-visible:outline-[#1B4E8A]">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  {[
                    ...(attributeColumns.length > 0 ? [{ key: null, label: '' }] : []),
                    { key: null, label: '#' },
                    ...(showItemNumber ? [{ key: 'itemNumber', label: 'Item #' }] : []),
                    { key: 'name', label: 'Item Name' },
                    { key: null, label: 'Type' },
                    { key: 'quantity', label: 'Qty' },
                    ...(showUnit ? [{ key: 'unit', label: 'Unit' }] : []),
                    ...(showShelfLife ? [{ key: 'shelfLife', label: 'Shelf Life' }] : []),
                    ...(showNotes ? [{ key: 'notes', label: 'Notes' }] : []),
                    { key: 'priority', label: 'Priority' },
                    { key: null, label: 'Confidence' },
                    { key: null, label: 'Status' },
                    { key: null, label: 'Actions' },
                  ].map((header, headerIndex) => (
                    <th
                      key={`${header.label}-${headerIndex}`}
                      className="sticky top-0 z-10 bg-gray-50 text-left px-4 py-3 text-xs text-gray-500"
                      style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}
                    >
                      {header.key ? (
                        <EditableLabel
                          value={columnLabel(header.key, header.label)}
                          onSave={next => renameColumn(header.key!, next)}
                        />
                      ) : (
                        header.label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && (
                  <tr><td colSpan={columnCount} className="px-6 py-12 text-center">
                    <PenLine size={24} className="mx-auto mb-3 text-gray-300" />
                    <div className="text-sm text-gray-500">No items yet. Add your first item below.</div>
                  </td></tr>
                )}
                {items.map((item, index) => {
                  const status = STATUS_CFG[item.status];
                  const priority = PRIORITY_CFG[item.priority];
                  const blocked = needsManualReview(item);
                  const isExpanded = expandedItems.has(item.id);
                  const missingName = item.status === 'missing' || !item.name;

                  const mainRow = (
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
                      {attributeColumns.length > 0 && (
                        <td className="pl-4 pr-0 py-3">
                          <button
                            onClick={() => toggleExpanded(item.id)}
                            aria-expanded={isExpanded}
                            aria-label={isExpanded ? 'Hide extra fields' : 'Show extra fields'}
                            className="p-1 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                          >
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </button>
                        </td>
                      )}
                      <td className="px-4 py-3 text-xs text-gray-400">{index + 1}</td>
                      {showItemNumber && (
                        <td className="px-4 py-3">
                          {item.itemNumber ? (
                            <span className="text-xs text-gray-500">{item.itemNumber}</span>
                          ) : (
                            <span className="text-xs text-gray-300 italic">-</span>
                          )}
                        </td>
                      )}
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
                        {!!item.reviewReasons?.length && <ul className="text-xs text-amber-700 mt-1">{item.reviewReasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
                        {item.manual && (
                          <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-500 font-medium">
                            <PenLine size={10} /> Manual
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs ${item.domain ? 'text-gray-700' : 'text-amber-700'}`}>
                          {item.domain ?? 'Choose in Edit'}

                        </span>
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
                      {showUnit && (
                        <td className="px-4 py-3">
                          {item.unit ? (
                            <span className="text-sm text-gray-500">{item.unit}</span>
                          ) : (
                            <span className="text-sm text-gray-400 italic">-</span>
                          )}
                        </td>
                      )}
                      {showShelfLife && (
                        <td className="px-4 py-3">
                          {item.shelfLife ? (
                            <span className="text-xs text-gray-500">{item.shelfLife}</span>
                          ) : (
                            <span className="text-xs text-gray-300 italic">-</span>
                          )}
                        </td>
                      )}
                      {showNotes && (
                        <td className="px-4 py-3 max-w-xs">
                          <span className={`text-xs ${item.notes ? 'text-gray-500' : 'text-gray-300 italic'}`}>
                            {item.notes || '-'}
                          </span>
                        </td>
                      )}
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
                          {status.icon} {item.verificationSource === 'ai' && item.status === 'verified' ? 'AI checked' : status.label}
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
                          {item.manual && (
                            <button
                              onClick={() => void removeItem(item.id)}
                              disabled={itemMutationPending || isAddingColumn}
                              aria-label={`Remove ${item.name}`}
                              title="Remove manual item"
                              className="p-1 rounded text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors disabled:opacity-40"
                            >
                              <X size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );

                  const detailRow =
                    attributeColumns.length > 0 && isExpanded ? (
                      <tr key={`${item.id}-details`} className="border-b border-gray-100 bg-gray-50/60">
                        <td colSpan={columnCount} className="px-12 py-3">
                          <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 max-w-3xl">
                            {attributeColumns.map(label => (
                              <Fragment key={label}>
                                {/* label (not the renamed text) is always the lookup key into
                                    item.attributes and the rename endpoint's columnKey - only
                                    what's displayed changes when the user renames it. */}
                                <dt className="text-xs text-gray-500" style={{ fontWeight: 600 }}>
                                  <EditableLabel
                                    value={columnLabel(label, label)}
                                    onSave={next => renameColumn(label, next)}
                                  />
                                </dt>
                                <dd
                                  className={`text-xs ${
                                    item.attributes?.[label] ? 'text-gray-700' : 'text-gray-300 italic'
                                  }`}
                                >
                                  {item.attributes?.[label] || '—'}
                                </dd>
                              </Fragment>
                            ))}
                          </dl>
                        </td>
                      </tr>
                    ) : null;

                  return detailRow ? [mainRow, detailRow] : mainRow;
                })}
              </tbody>
            </table>
          </div>

          <button
            onClick={openAdd}
            disabled={itemMutationPending || isAddingColumn}
            className="mt-3 w-full flex items-center justify-center gap-2 px-4 py-3 border border-dashed border-gray-300 rounded-xl text-sm text-[#1B4E8A] hover:border-[#1B4E8A]/50 hover:bg-blue-50/40 transition-colors font-medium disabled:opacity-50"
          >
            <Plus size={16} /> Add item manually
          </button>

          <div className="mt-5 flex items-center justify-between gap-4">
            <div className="text-xs leading-relaxed">
              {items.length === 0 ? (
                <span className="text-gray-500">Add at least one item to continue.</span>
              ) : blockedItems.length > 0 ? (
                <span className="text-amber-700" style={{ fontWeight: 500 }}>
                  <AlertTriangle size={12} className="inline mr-1 mb-0.5" />
                  {blockedItems.map(item => item.name || '(missing item)').join(', ')} must be reviewed before proceeding.
                </span>
              ) : needsReview > 0 ? (
                <span className="text-amber-600">
                  {needsReview} item(s) still flagged for review. Click Verify or Edit to confirm them.
                </span>
              ) : items.some(item => !item.domain) ? (
                <span className="text-amber-700">Choose Medicine or Equipment for every item before matching.</span>
              ) : (
                <span className="text-green-700" style={{ fontWeight: 500 }}>
                  All items verified and classified. Ready to proceed.
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

        <div className="w-full xl:w-56 flex-shrink-0 xl:sticky xl:top-6 space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-gray-900 text-sm mb-4" style={{ fontWeight: 600 }}>
              {isManualRequest ? 'Request Summary' : 'Extraction Summary'}
            </h3>
            <SummaryRow label="Total rows" value={items.length} />
            <SummaryRow label="Verified" value={verified} icon={<CheckCircle2 size={13} className="text-green-500" />} tone="green" />
            <SummaryRow label="Needs Verification" value={needsReview} icon={<AlertCircle size={13} className="text-amber-500" />} tone="amber" />
            <SummaryRow label="Low Confidence" value={lowConfidence} icon={<AlertTriangle size={13} className="text-red-500" />} tone="red" />
            <SummaryRow label="Missing" value={missing} icon={<HelpCircle size={13} className="text-red-500" />} tone="red" last />
            {manualCount > 0 && <SummaryRow label="Added manually" value={manualCount} icon={<PenLine size={13} className="text-slate-500" />} last />}
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
                {!editingPartner && !partnerDetails.confirmed && (
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
                {(['partner', 'region', 'contact'] as const).map(key => (
                  <div key={key}>
                    <div className="text-xs text-gray-400 mb-0.5">{partnerLabel(key)}</div>
                    <input
                      className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      value={partnerDraft[key]}
                      onChange={event => setPartnerDraft(draft => draft && { ...draft, [key]: event.target.value })}
                    />
                  </div>
                ))}
                <div className="text-xs text-gray-500">{requestId ? <>System request ID: <span className="font-mono text-gray-700">{partnerDetails.requestId}</span></> : 'Request saved when you add the first item.'}</div>
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
                    Save
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="space-y-2.5 mb-4">
                  {[
                    { label: 'Partner', value: partnerDetails.partner },
                    { label: 'Region', value: partnerDetails.region },
                    { label: 'Request ID', value: partnerDetails.requestId || 'Assigned when the first item is added' },
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
                    onClick={() => void confirmPartnerDetails()}
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
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6"
          onClick={event => {
            if (event.target === event.currentTarget && !isSavingItem) setEditingItem(null);
          }}>
          <div role="dialog" aria-modal="true" aria-labelledby="item-dialog-title" className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col overflow-hidden">
            <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between shrink-0">
              <div>
                <h3 id="item-dialog-title" className="text-gray-900">
                  {isNewItem ? 'Add Item Manually' : editingItem.manual ? 'Edit Manual Item' : editingItem.status === 'missing' ? 'Complete Missing Information' : 'Edit Extracted Item'}
                </h3>
                <p className="text-gray-500 text-sm mt-0.5">{editingItem.manual ? 'Not linked to a source document' : `Row #${sourceReferences[editingItem.id]?.row ?? editingItem.id} in source document`}</p>
              </div>
              <button disabled={isSavingItem} aria-label="Close item dialog" onClick={() => setEditingItem(null)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors">
                <X size={18} />
              </button>
            </div>

            <div className="px-6 py-5 min-h-0 overflow-y-auto overscroll-contain">
              {itemError && <div className="mb-4"><ErrorPanel message={itemError} /></div>}
              <SourceReferencePanel item={editingItem} reference={sourceReferences[editingItem.id]} />
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                      Item #
                    </label>
                    <input
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      value={editValues.itemNumber ?? ''}
                      onChange={event =>
                        setEditValues(values => ({ ...values, itemNumber: event.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                      Shelf Life
                    </label>
                    <input
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      placeholder="e.g. 24 months"
                      value={editValues.shelfLife ?? ''}
                      onChange={event =>
                        setEditValues(values => ({ ...values, shelfLife: event.target.value }))
                      }
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                    Item Name
                  </label>
                  <input
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                    aria-label="Item Name"
                    autoFocus={editingItem.manual}
                    placeholder={editingItem.manual ? 'e.g. Ceftriaxone 1g Powder for Injection' : ''}
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
                      aria-label="Quantity"
                      min={1}
                      step={1}
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
                    <label htmlFor="item-unit" className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                      Unit
                      {unitInferred && <span id="item-unit-inference" className="ml-2 text-amber-700 font-normal">AI inferred</span>}
                    </label>
                    <input
                      id="item-unit"
                      aria-describedby={unitInferred ? 'item-unit-inference' : undefined}
                      className={`w-full border rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] ${unitInferred ? 'border-amber-400 bg-amber-50' : 'border-gray-300 bg-white'}`}
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
                  <label htmlFor="item-type" className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                    Product type (required)
                    {typeInferred && <span id="item-type-inference" className="ml-2 text-amber-700 font-normal">AI inferred</span>}
                  </label>
                  <select
                    id="item-type"
                    aria-label="Product type"
                    aria-describedby={typeInferred ? 'item-type-inference' : undefined}
                    className={`w-full border rounded-lg px-3 py-2 text-sm ${typeInferred ? 'border-amber-400 bg-amber-50' : 'border-gray-300 bg-white'}`}
                    value={editValues.domain ?? ''}
                    onChange={event => setEditValues(values => ({
                      ...values,
                      domain: event.target.value as ExtractedItem['domain'],
                    }))}
                  >
                    <option value="">Choose type</option>
                    <option value="medicine">Medicine</option>
                    <option value="equipment">Equipment</option>
                  </select>
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

            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3 shrink-0">
              <button
                disabled={isSavingItem}
                onClick={() => setEditingItem(null)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                style={{ fontWeight: 500 }}
              >
                Cancel
              </button>
              <button
                onClick={() => void saveEdit()}
                disabled={!canSave || isSavingItem}
                className="px-5 py-2 bg-[#1B4E8A] text-white rounded-lg text-sm hover:bg-[#163d6d] transition-colors disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed"
                style={{ fontWeight: 600 }}
              >
                {isSavingItem ? 'Saving…' : isNewItem ? 'Add Item' : 'Save & Mark Verified'}
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
              Once you proceed, the item list will be locked. The matching step requires
              significant compute and cannot be undone without starting a new request.
            </p>
            <div className="mt-5 bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div className="text-xs text-gray-500" style={{ fontWeight: 600 }}>
                Summary
              </div>
              <div className="text-xs text-gray-700 mt-1">
                {items.length} items · {verified} verified{manualCount > 0 && ` · ${manualCount} manual`} · Partner: {partnerDetails.partner || '—'}
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

  if (item.manual) {
    return (
      <div className="border border-dashed border-slate-300 bg-slate-50 rounded-xl p-4 mb-5 flex items-start gap-2.5">
        <PenLine size={14} className="text-slate-500 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-slate-600 leading-relaxed">
          <span className="font-bold">Manual entry.</span> This item is added by you and will be marked
          as verified. Name, a positive whole-number quantity and product type are required.
        </div>
      </div>
    );
  }

  return (
    <div className={`border rounded-xl p-4 mb-5 ${isMissing ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'}`}>
      <div className="flex items-center gap-2 mb-2">
        <BookOpen size={14} className={isMissing ? 'text-red-500' : 'text-amber-600'} />
        <span className={`text-xs ${isMissing ? 'text-red-800' : 'text-amber-800'}`} style={{ fontWeight: 700 }}>
          Source Reference - Page {reference?.page ?? '-'}, Row {reference?.row ?? '-'}
        </span>
      </div>
      <div
        className={`mt-1.5 rounded-lg px-3 py-2 text-xs leading-relaxed italic ${
          isMissing ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'
        }`}
      >
        {reference?.excerpt ?? 'No source reference available'}
      </div>
      {!!item.reviewReasons?.length && <ul className="mt-3 text-xs text-amber-800 list-disc pl-4">{item.reviewReasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
      <div className={`flex items-center gap-1.5 mt-2 text-xs ${isMissing ? 'text-red-600' : 'text-amber-600'}`}>
        <Info size={11} />
        {isMissing
          ? 'Item name extracted. Quantity could not be read. Please enter it manually.'
          : item.verificationSource === 'ai' ? `AI checked against the source${item.confidence == null ? '' : ` · ${item.confidence}% confidence`}` : item.confidence == null ? 'Check against the original source' : `Extracted with ${item.confidence}% confidence`}
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
