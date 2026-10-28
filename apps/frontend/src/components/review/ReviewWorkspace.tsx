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
  RotateCcw,
  SlidersHorizontal,
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
} from '../../api/client';
import type {
  ExtractedItem,
  ItemStatus,
  ManualItemCreate,
  PartnerDetails,
  Priority,
  ReviewResponse,
  SourceReference,
} from '../../api/types';
import { ErrorPanel, LoadingPanel } from '../ScreenState';
import { WorkflowStepper } from '../WorkflowStepper';
import {
  BulkEdit,
  GuidedReview,
  OperationPreview,
  ReviewCheckbox,
  ReviewOverview,
  ReviewToast,
  ViewNavigation,
  problemLabels,
  reviewButton,
  reviewInput,
  type ReviewView,
} from './ReviewTools';
import { useReviewOperations } from '../../features/review/use-review-operations';
import { reviewSteps } from '../../features/review/task-queue';
import { filterItems, isReady, reviewPresentation, toggleSelection } from '../../features/review/model';

type ReviewWorkspaceProps = {
  requestId: string | null;
  initialData?: ReviewResponse | null;
  onContinue: () => void;
  onCreateManual?: (
    item: ManualItemCreate,
    partner: PartnerDetails,
    columnLabels: Record<string, string>,
  ) => Promise<ReviewResponse>;
};

const PRIORITY_CFG: Record<Priority, { label: string; color: string; bg: string }> = {
  critical: { label: 'Critical', color: 'text-red-700', bg: 'bg-red-100' },
  high: { label: 'High', color: 'text-orange-700', bg: 'bg-orange-100' },
  medium: { label: 'Medium', color: 'text-yellow-700', bg: 'bg-yellow-100' },
  low: { label: 'Low', color: 'text-gray-600', bg: 'bg-gray-100' },
};

const STATUS_CFG: Record<ItemStatus, { label: string; icon: ReactNode; color: string; bg: string }> = {
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
  missing: { label: 'Missing', icon: <HelpCircle size={11} />, color: 'text-red-700', bg: 'bg-red-100' },
};

/** Units the extractor filled in carry their reason in inferredFields.unit; the backend's default
 * (no unit in the request -> Stück) is labelled differently from an AI inference. */
function unitSourceTag(item: ExtractedItem): string | null {
  const evidence = item.inferredFields?.unit;
  if (!evidence) return null;
  return evidence.startsWith('No unit in the request') ? 'default' : 'AI inferred';
}

function needsManualReview(item: ExtractedItem) {
  return (
    item.status === 'low_confidence' ||
    item.status === 'missing' ||
    !item.domain ||
    !!item.reviewReasons?.length
  );
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
        onFocus={(event) => event.target.select()}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.currentTarget.blur();
          } else if (event.key === 'Escape') {
            setDraft(value);
            setIsEditing(false);
          }
        }}
        onClick={(event) => event.stopPropagation()}
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

export function ReviewWorkspace({
  requestId,
  initialData,
  onContinue,
  onCreateManual,
}: ReviewWorkspaceProps) {
  const [data, setData] = useState<ReviewResponse | null>(initialData ?? null);
  const [items, setItems] = useState<ExtractedItem[]>(initialData?.items ?? []);
  const [partnerDetails, setPartnerDetails] = useState<PartnerDetails | null>(initialData?.partner ?? null);
  const [editingItem, setEditingItem] = useState<ExtractedItem | null>(null);
  const itemDialog = useRef<HTMLFormElement>(null);
  const [isNewItem, setIsNewItem] = useState(false);
  const [isSavingItem, setIsSavingItem] = useState(false);
  const [removingItemId, setRemovingItemId] = useState<number | null>(null);
  const [itemError, setItemError] = useState<string | null>(null);
  const [showItemValidation, setShowItemValidation] = useState(false);
  const [editValues, setEditValues] = useState<Partial<ExtractedItem>>({});
  const unitInferred = Boolean(editingItem?.inferredFields?.unit) && editValues.unit === editingItem?.unit;
  const typeInferred =
    Boolean(editingItem?.inferredFields?.type) && editValues.domain === editingItem?.domain;
  useEffect(() => {
    const dialog = itemDialog.current;
    if (!editingItem || !dialog) return;
    const previous = document.activeElement;
    if (!dialog.contains(previous)) dialog.focus();
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const controls = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled)',
        ),
      );
      const first = controls[0],
        last = controls.at(-1);
      if (!first) {
        event.preventDefault();
        return;
      }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog)) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener('keydown', trapFocus);
    return () => {
      dialog.removeEventListener('keydown', trapFocus);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [editingItem?.id]);
  useEffect(() => {
    if (!editingItem || isNewItem) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSavingItem) {
        event.preventDefault();
        setEditingItem(null);
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [editingItem, isNewItem, isSavingItem]);
  const [editingPartner, setEditingPartner] = useState(false);
  const [isSavingPartner, setIsSavingPartner] = useState(false);
  const [partnerDraft, setPartnerDraft] = useState<PartnerDetails | null>(null);
  const [partnerError, setPartnerError] = useState<string | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(!initialData);
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  const [columnLabels, setColumnLabels] = useState<Record<string, string>>(initialData?.columnLabels ?? {});
  const [availableColumns, setAvailableColumns] = useState<string[]>(initialData?.availableColumns ?? []);
  const [newColumnName, setNewColumnName] = useState('');
  const [isAddingColumn, setIsAddingColumn] = useState(false);
  const [isReviewingAi, setIsReviewingAi] = useState(false);
  const busyDialog = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<ReviewView>(
    typeof initialData?.reviewRevision === 'number' && initialData.source.fileName ? 'overview' : 'all',
  );
  const initializedView = useRef(initialData ? requestId : null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [showRemoved, setShowRemoved] = useState(false);
  const [showBulkEdit, setShowBulkEdit] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsVisit, setDetailsVisit] = useState(0);
  const refreshReview = (review: ReviewResponse) => {
    setData(review);
    setItems(review.items);
    setPartnerDetails(review.partner);
    setColumnLabels(review.columnLabels ?? {});
    setAvailableColumns(review.availableColumns ?? []);
  };
  const operations = useReviewOperations(requestId, data, refreshReview);
  const structuredReview = typeof data?.reviewRevision === 'number';
  useEffect(() => {
    if (data && initializedView.current !== requestId) {
      initializedView.current = requestId;
      setView(typeof data.reviewRevision === 'number' && data.source.fileName ? 'overview' : 'all');
    }
  }, [data, requestId]);
  useEffect(() => {
    setSelected(new Set());
  }, [search, stateFilter, typeFilter, categoryFilter, showRemoved]);
  useEffect(() => {
    if (operations.toast?.operationId) {
      setEditingItem(null);
      setShowBulkEdit(false);
      setSelected(new Set());
    }
  }, [operations.toast?.operationId]);
  const categoryItems = new Set(
    (data?.issues ?? [])
      .filter((issue) => issue.state === 'open' && issue.category === categoryFilter)
      .flatMap((issue) => (issue.itemId === null ? (issue.itemIds ?? []) : [issue.itemId])),
  );
  const tableItems = showRemoved ? (data?.removedItems ?? []) : items;
  const displayItems = filterItems(
    tableItems,
    search,
    stateFilter,
    typeFilter,
    categoryFilter,
    categoryItems,
  );
  const selectedItems = tableItems.filter((item) => selected.has(item.id));
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
      refreshReview(reviewed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to review with AI');
    } finally {
      setIsReviewingAi(false);
    }
  };

  // key is a core-field key ('name', 'quantity', ...) or an attribute column's own label - see
  // ReviewResponse.columnLabels. Optimistic: applies locally first so the header doesn't flicker
  // back to its old text while the request is in flight, then reconciles with the server's copy.
  const renameColumn = (key: string, label: string) => {
    setColumnLabels((previous) => ({ ...previous, [key]: label }));
    if (!requestId) return;
    updateColumnLabel(requestId, key, label)
      .then(async (labels) => {
        setColumnLabels(labels);
        if (structuredReview) refreshReview(await getReview(requestId));
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : 'Unable to rename column');
      });
  };

  const columnLabel = (key: string, fallback: string) => columnLabels[key] ?? fallback;

  const existingColumnLabels = useMemo(
    () => new Set((data?.attributeColumns ?? []).map((label) => label.toLowerCase())),
    [data],
  );

  // Passes the same string as both displayName and hint: it's either picked verbatim from
  // availableColumns (an exact detected header, so the deterministic hint match resolves it for
  // free) or typed freely by the user, in which case it still guides the LLM fallback match the
  // same way a hint would - see CustomColumnRequest / app.parsing.custom_columns.
  const sheets = data?.sheets ?? [];

  const submitNewColumn = async () => {
    if (!requestId) return;
    const trimmed = newColumnName.trim();
    if (
      !trimmed ||
      isAddingColumn ||
      isSavingItem ||
      removingItemId !== null ||
      existingColumnLabels.has(trimmed.toLowerCase())
    ) {
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
    setExpandedItems((previous) => {
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
      .then((response) => {
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
      .catch((caught) => {
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
        (data?.sourceReferences ?? []).map((reference) => [reference.itemId, reference]),
      ) as Record<number, SourceReference>,
    [data],
  );

  // Columns vary per uploaded file - a bare name/qty/unit sheet contributes none, while a full
  // RFQ form contributes several. Fall back to whatever the items carry if the server didn't
  // send an explicit ordering.
  const attributeColumns =
    data?.attributeColumns && data.attributeColumns.length > 0
      ? data.attributeColumns
      : Array.from(new Set(items.flatMap((item) => Object.keys(item.attributes ?? {}))));

  // Optional core columns only earn their width when the file populated them - the same
  // adaptive rule the extra columns follow, so a sparse request form stays readable.
  const showItemNumber = items.some((item) => item.itemNumber);
  const showUnit = items.some((item) => item.unit);
  const showShelfLife = items.some((item) => item.shelfLife);
  const showNotes = items.some((item) => item.notes);
  const columnCount =
    (structuredReview ? 7 : 8) +
    (structuredReview ? 1 : 0) +
    (attributeColumns.length > 0 ? 1 : 0) +
    [showItemNumber, showUnit, showShelfLife, showNotes].filter(Boolean).length;

  const verified = items.filter((item) => item.status === 'verified').length;
  const manualCount = items.filter((item) => item.manual).length;
  const isManualRequest = !!data && !data.source.fileName;
  const itemMutationPending = isReviewingAi || isSavingItem || removingItemId !== null || operations.busy;
  const allVerified =
    (structuredReview
      ? !!data?.canStartMatching
      : items.length > 0 &&
        verified === items.length &&
        items.every((item) => item.domain && !item.reviewReasons?.length)) &&
    !itemMutationPending &&
    !isAddingColumn &&
    !operations.pending;
  const blockedItems = items.filter(needsManualReview);

  const openEdit = (item: ExtractedItem) => {
    if (isReviewingAi) return;
    setIsNewItem(false);
    setItemError(null);
    setShowItemValidation(false);
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
      id: 0,
      name: '',
      quantity: null,
      unit: '',
      notes: '',
      itemNumber: '',
      shelfLife: '',
      attributes: {},
      priority: 'medium',
      confidence: null,
      status: 'verified',
      domain: null,
      manual: true,
    };
    openEdit(item);
    setIsNewItem(true);
  };

  const validName = !!editValues.name?.trim();
  const validQuantity = Number.isInteger(editValues.quantity) && (editValues.quantity ?? 0) > 0;
  const validType = editValues.domain === 'medicine' || editValues.domain === 'equipment';
  const canSave = validName && validQuantity && validType;
  const nameInvalid = showItemValidation && !validName;
  const quantityInvalid = showItemValidation && !validQuantity;
  const typeInvalid = showItemValidation && !validType;
  const invalidFieldLabels = [
    !validName && 'Item name',
    !validQuantity && 'Quantity',
    !validType && 'Product type',
  ].filter(Boolean);

  const saveEdit = async () => {
    if (!editingItem || isSavingItem) {
      return;
    }
    if (!canSave) {
      setShowItemValidation(true);
      const firstInvalid = !validName ? 'item-name' : !validQuantity ? 'item-quantity' : 'item-type';
      const field = itemDialog.current?.querySelector<HTMLElement>(`#${firstInvalid}`);
      field?.focus({ preventScroll: true });
      field?.scrollIntoView({ block: 'center', inline: 'nearest' });
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
          payload,
          editingPartner && partnerDraft ? partnerDraft : partnerDetails,
          columnLabels,
        );
        setEditingItem(null);
        return;
      }
      if (structuredReview && !isNewItem) {
        const changes = Object.fromEntries(
          Object.entries(payload).filter(([key, value]) => value !== editingItem[key as keyof ExtractedItem]),
        );
        if (!Object.keys(changes).length) {
          setEditingItem(null);
          return;
        }
        await operations.preview({ action: 'edit', itemIds: [editingItem.id], changes });
        return;
      }
      const updated = isNewItem
        ? await addManualItem(requestId, payload)
        : await updateItem(requestId, editingItem.id, payload);
      if (structuredReview) refreshReview(await getReview(requestId));
      else
        setItems((prev) =>
          isNewItem ? [...prev, updated] : prev.map((item) => (item.id === updated.id ? updated : item)),
        );
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
    if (structuredReview) {
      await operations.preview({ action: 'remove', itemIds: [id] });
      return;
    }
    setRemovingItemId(id);
    try {
      await removeManualItem(requestId, id);
      setItems((previous) => previous.filter((item) => item.id !== id));
      setExpandedItems((previous) => {
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
    const item = items.find((value) => value.id === id);
    if (item && !item.domain) {
      openEdit(item);
      return;
    }
    if (structuredReview) {
      await operations.preview({ action: 'verify', itemIds: [id] });
      return;
    }
    try {
      const updated = await verifyItem(requestId, id);
      setItems((prev) => prev.map((item) => (item.id === id ? updated : item)));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to verify item');
    }
  };

  const startEditPartner = () => {
    if (partnerDetails && !isSavingPartner) {
      setPartnerDraft({ ...partnerDetails });
      setEditingPartner(true);
      setPartnerError(null);
    }
  };

  const savePartner = async (confirmAfter = false) => {
    const draft = partnerDraft ?? partnerDetails;
    if (!draft || !partnerDetails || isSavingPartner) return;
    setIsSavingPartner(true);
    setPartnerError(null);
    try {
      let updated = partnerDetails;
      const changed = (['partner', 'region', 'contact'] as const).some(
        (key) => draft[key] !== partnerDetails[key],
      );
      if (changed) {
        updated = requestId
          ? await updatePartner(requestId, {
              partner: draft.partner,
              region: draft.region,
              requestId: draft.requestId,
              contact: draft.contact,
            })
          : { ...draft, confirmed: false };
        // Preserve a successful save even if the subsequent confirmation needs a retry.
        setPartnerDetails({ ...partnerDetails, ...updated });
      }
      if (confirmAfter) {
        const confirmed = requestId ? await confirmPartner(requestId) : { confirmed: true };
        updated = { ...updated, ...confirmed };
        setDetailsOpen(false);
      }
      setPartnerDetails({ ...partnerDetails, ...updated });
      setPartnerDraft(null);
      setEditingPartner(false);
    } catch (caught) {
      setPartnerError(caught instanceof Error ? caught.message : 'Unable to save request details');
    } finally {
      setIsSavingPartner(false);
    }
  };

  const openRequestDetails = () => {
    setView('guided');
    setDetailsOpen(true);
    setDetailsVisit((visit) => visit + 1);
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

  const requestDetailsCard = (
    <section aria-label="Request details step" className="p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-semibold">Review request details</h2>
          <p className="text-sm text-gray-500 mt-1">
            All fields are optional. Leave unavailable details empty.
          </p>
        </div>
        {partnerDetails.confirmed && !editingPartner && (
          <button
            type="button"
            disabled={isSavingPartner}
            aria-label="Edit partner details"
            onClick={startEditPartner}
            className={reviewButton}
          >
            <Pencil size={12} className="inline mr-1.5" /> Edit
          </button>
        )}
      </div>
      {partnerError && (
        <p role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {partnerError}
        </p>
      )}
      {editingPartner || !partnerDetails.confirmed ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void savePartner(true);
          }}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            {(['partner', 'region', 'contact'] as const).map((key) => (
              <label key={key} className="block text-xs text-gray-500">
                {partnerLabel(key)} <span className="text-gray-400">(optional)</span>
                <input
                  className={`${reviewInput} block w-full mt-1`}
                  value={(partnerDraft ?? partnerDetails)[key]}
                  disabled={isSavingPartner}
                  onChange={(event) => {
                    setPartnerDraft((draft) => ({
                      ...(draft ?? partnerDetails),
                      [key]: event.target.value,
                      confirmed: false,
                    }));
                    setEditingPartner(true);
                  }}
                />
              </label>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-4">
            System request ID: {partnerDetails.requestId || 'Assigned when the first item is added'}
          </p>
          <div className="flex flex-wrap justify-end gap-2 mt-5">
            {editingPartner && (
              <>
                <button
                  type="button"
                  className={reviewButton}
                  disabled={isSavingPartner}
                  onClick={() => {
                    setEditingPartner(false);
                    setPartnerDraft(null);
                    setPartnerError(null);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={reviewButton}
                  disabled={isSavingPartner}
                  onClick={() => void savePartner()}
                >
                  {isSavingPartner ? 'Saving…' : 'Save'}
                </button>
              </>
            )}
            <button
              type="submit"
              disabled={isSavingPartner}
              className="px-4 py-2 rounded-lg text-sm bg-[#1B4E8A] text-white disabled:opacity-50"
            >
              {isSavingPartner ? 'Saving…' : 'Save & confirm details'}
            </button>
          </div>
        </form>
      ) : (
        <>
          <dl className="grid gap-4 sm:grid-cols-3">
            {(['partner', 'region', 'contact'] as const).map((key) => (
              <div key={key}>
                <dt className="text-xs text-gray-500">{partnerLabel(key)}</dt>
                <dd className="mt-1 text-sm">{partnerDetails[key] || 'Not specified'}</dd>
              </div>
            ))}
          </dl>
          <div className="flex items-center justify-between mt-5">
            <span className="text-xs text-teal-700 flex items-center gap-1.5">
              <CheckCircle2 size={14} /> Details confirmed
            </span>
            <button
              type="button"
              className={reviewButton}
              onClick={() => {
                setDetailsOpen(false);
                setView('all');
              }}
            >
              Back to items
            </button>
          </div>
        </>
      )}
    </section>
  );

  return (
    <div className="p-4 lg:p-5" aria-busy={isReviewingAi}>
      {isReviewingAi &&
        createPortal(
          <div className="fixed inset-0 z-[100] bg-black/40 flex items-center justify-center p-6">
            <div
              ref={busyDialog}
              role="dialog"
              aria-modal="true"
              aria-labelledby="ai-review-loading"
              tabIndex={-1}
              onKeyDown={(event) => {
                if (event.key === 'Tab') event.preventDefault();
              }}
              className="rounded-2xl bg-white p-8 shadow-xl text-center outline-none"
            >
              <Loader2 size={32} className="animate-spin text-[#1B4E8A] mx-auto mb-4" aria-hidden="true" />
              <h2 id="ai-review-loading" className="text-gray-900">
                Checking items with AI
              </h2>
              <p className="text-sm text-gray-500 mt-2" role="status">
                Please wait while the copied values are checked.
              </p>
            </div>
          </div>,
          document.body,
        )}
      <div className="bg-white rounded-xl border border-gray-200 px-3 py-2 mb-3">
        <WorkflowStepper currentStep="review" />
      </div>

      {error && (
        <div className="mb-4">
          <ErrorPanel message={error} />
        </div>
      )}
      {operations.error && !operations.pending && (
        <div className="mb-4">
          <ErrorPanel message={operations.error} />
        </div>
      )}
      <OperationPreview operations={operations} />
      <ReviewToast operations={operations} />
      <div className="space-y-3">
        <div className="w-full min-w-0">
          <header className="mb-3" aria-label="Review header">
            <div className="flex items-center justify-between gap-3">
              <h1 className="text-lg font-semibold text-gray-900">
                {isManualRequest ? 'Build manual request' : 'Review extracted items'}
              </h1>
              {!isManualRequest && (
                <details
                  className="relative text-xs text-gray-500 shrink-0"
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                      event.currentTarget.open = false;
                      event.currentTarget.querySelector('summary')?.focus();
                    }
                  }}
                  onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
                  }}
                >
                  <summary className="cursor-pointer py-1">
                    Extraction details
                    {data.parserWarnings?.length ? ` · ${data.parserWarnings.length} notes` : ''}
                  </summary>
                  <div
                    role="status"
                    className="review-fade absolute right-0 top-full mt-2 z-30 w-[min(32rem,85vw)] max-h-[70vh] overflow-auto space-y-1 rounded-xl border border-gray-200 bg-white shadow-lg p-4"
                  >
                    {data.parserWarnings?.some(
                      (warning) => !warning.includes('Ignored supplier/admin columns:'),
                    ) && <p className="font-medium">Import notes</p>}
                    {data.parserWarnings?.some((warning) =>
                      warning.includes('Ignored supplier/admin columns:'),
                    ) && <p className="font-medium">Source column notes</p>}
                    {(data.parserWarnings ?? []).map((warning, index) => (
                      <p key={index}>{warning}</p>
                    ))}
                    {data.reviewSummary?.status && (
                      <p>
                        {data.reviewSummary.checked ?? 0} rows AI checked ·{' '}
                        {data.reviewSummary.corrected ?? 0} corrected ·{' '}
                        {items.filter((item) => item.status !== 'verified').length} unresolved
                      </p>
                    )}
                    {data.reviewSummary?.message && <p>{data.reviewSummary.message}</p>}
                    {data.reviewSummary?.status !== 'completed' && (
                      <button
                        type="button"
                        className={reviewButton}
                        disabled={itemMutationPending || !!editingItem}
                        onClick={() => void runAiReview()}
                      >
                        Review with AI
                      </button>
                    )}
                    {sheets.length > 1 && (
                      <p>
                        Worksheets:{' '}
                        {(data.selectedSheets?.length
                          ? data.selectedSheets
                          : [data.selectedSheet ?? sheets[0].name]
                        ).join(', ')}
                      </p>
                    )}
                    <p className="pt-3 text-gray-500">
                      Additional source attributes can influence matching. Extract another only when needed.
                    </p>
                    <div className="border-t border-gray-100 pt-3 mt-3 flex items-center gap-2 flex-wrap">
                      <div className="flex items-center gap-1.5 text-gray-500 flex-shrink-0">
                        <ListPlus size={14} />
                        <span className="text-xs" style={{ fontWeight: 600 }}>
                          Add column
                        </span>
                      </div>
                      <input
                        type="text"
                        aria-label="Additional attribute"
                        list="available-columns-suggestions"
                        placeholder={
                          availableColumns.length > 0
                            ? 'Pick a detected column or type your own...'
                            : 'Type a column name (e.g. Batch Number)...'
                        }
                        value={newColumnName}
                        onChange={(event) => setNewColumnName(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            void submitNewColumn();
                          }
                        }}
                        disabled={isAddingColumn || isReviewingAi || itemMutationPending}
                        className="flex-1 min-w-[200px] border border-gray-300 rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] disabled:bg-gray-50"
                      />
                      <datalist id="available-columns-suggestions">
                        {availableColumns.map((column) => (
                          <option key={column} value={column} />
                        ))}
                      </datalist>
                      <button
                        onClick={() => void submitNewColumn()}
                        disabled={
                          !newColumnName.trim() || isAddingColumn || isReviewingAi || itemMutationPending
                        }
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs flex-shrink-0 transition-colors ${
                          newColumnName.trim() && !isAddingColumn
                            ? 'bg-[#1B4E8A] text-white hover:bg-[#163d6d]'
                            : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                        }`}
                        style={{ fontWeight: 600 }}
                      >
                        <Plus size={12} /> {isAddingColumn ? 'Adding...' : 'Add'}
                      </button>
                    </div>
                  </div>
                </details>
              )}
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs text-gray-500 min-w-0">
              {isManualRequest ? (
                <PenLine size={13} className="shrink-0" />
              ) : (
                <FileText size={13} className="shrink-0" />
              )}
              <span className="truncate font-medium max-w-[45%]" title={data.source.fileName}>
                {isManualRequest ? 'Manual request' : data.source.fileName}
              </span>
              <span className="shrink-0">
                · {isManualRequest ? `${items.length} items` : `${data.source.rowsDetected} rows`}
              </span>
              <span className="truncate">· {partnerDetails.partner || 'Partner not specified'}</span>
              {manualCount > 0 && !isManualRequest && (
                <span className="shrink-0 hidden lg:inline">· {manualCount} added manually</span>
              )}
            </div>
          </header>
          <div className="flex justify-between items-center gap-2 mb-3" aria-label="Review navigation">
            <ViewNavigation view={view} setView={setView} />
            <div className="flex gap-2 shrink-0">
              <button
                type="button"
                aria-label="Request details"
                title={partnerDetails.confirmed ? 'Details confirmed' : 'Request details not confirmed'}
                className="px-2.5 py-1.5 rounded-md border border-gray-200 text-xs hover:bg-gray-50 flex items-center gap-1.5"
                disabled={isSavingPartner || isReviewingAi}
                onClick={openRequestDetails}
              >
                {partnerDetails.confirmed ? (
                  <CheckCircle2 size={13} className="text-teal-600" />
                ) : (
                  <Info size={13} className="text-amber-600" />
                )}{' '}
                Request details
              </button>
              <button
                type="button"
                aria-label="Undo last action"
                className="px-2.5 py-1.5 rounded-md border border-gray-200 text-xs hover:bg-gray-50 disabled:opacity-40 flex items-center gap-1.5"
                disabled={!operations.lastUndoId || itemMutationPending}
                onClick={() => void operations.undo()}
              >
                <RotateCcw size={13} /> Undo
              </button>
            </div>
          </div>
          {view === 'overview' && (
            <ReviewOverview
              data={{ ...data, tasks: reviewSteps(data.tasks ?? [], !partnerDetails.confirmed) }}
              onStart={() => setView('guided')}
              onAll={() => setView('all')}
            />
          )}
          <GuidedReview
            key={data.requestId}
            data={data}
            hidden={view !== 'guided'}
            operations={operations}
            onEdit={openEdit}
            onAll={() => setView('all')}
            requestDetails={{
              content: requestDetailsCard,
              confirmed: partnerDetails.confirmed,
              open: detailsOpen,
              visit: detailsVisit,
            }}
          />
          <div hidden={view !== 'all'}>
            {structuredReview &&
              (data.issues ?? []).some((issue) => issue.scope === 'table' && issue.state === 'open') && (
                <div className="mb-3 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 flex items-center justify-between gap-3 text-sm text-[#1B4E8A]">
                  <span>
                    The source columns need one shared confirmation. You do not need to verify each row.
                  </span>
                  <button type="button" className={reviewButton} onClick={() => setView('guided')}>
                    Review source columns
                  </button>
                </div>
              )}
            {structuredReview && (
              <div className="bg-white border border-gray-200 rounded-xl p-2 mb-2 space-y-2">
                <div role="search" className="flex items-center gap-2">
                  <input
                    aria-label="Search items"
                    placeholder="Search items…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className={`${reviewInput} py-1.5 flex-1 min-w-0`}
                  />
                  <span
                    className={`text-xs whitespace-nowrap hidden sm:inline ${data.reviewCounts?.affected ? 'text-amber-700' : 'text-teal-700'}`}
                    title={`${displayItems.length} ${showRemoved ? 'removed' : 'active'} items shown. Selection applies to filtered rows.`}
                  >
                    {showRemoved
                      ? `${displayItems.length} removed`
                      : `${data.reviewCounts?.ready ?? 0}/${items.length} ready`}
                  </span>
                  <details
                    className="relative shrink-0"
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') {
                        event.currentTarget.open = false;
                        event.currentTarget.querySelector('summary')?.focus();
                      }
                    }}
                    onBlur={(event) => {
                      if (!event.currentTarget.contains(event.relatedTarget))
                        event.currentTarget.open = false;
                    }}
                  >
                    <summary className="list-none cursor-pointer px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs flex items-center gap-1.5 hover:bg-gray-50">
                      <SlidersHorizontal size={13} /> Filters
                      {[stateFilter, typeFilter, categoryFilter].some((filter) => filter !== 'all') &&
                        ` (${[stateFilter, typeFilter, categoryFilter].filter((filter) => filter !== 'all').length})`}
                    </summary>
                    <div
                      className="review-fade absolute right-0 top-full mt-2 z-20 w-64 bg-white border border-gray-200 rounded-xl shadow-lg p-3 space-y-2"
                      aria-label="Item filters"
                    >
                      <select
                        aria-label="Review state filter"
                        value={stateFilter}
                        onChange={(e) => setStateFilter(e.target.value)}
                        className={`${reviewInput} w-full`}
                      >
                        <option value="all">All states</option>
                        <option value="ready">Ready</option>
                        <option value="needs">Needs review</option>
                      </select>
                      <select
                        aria-label="Product type filter"
                        value={typeFilter}
                        onChange={(e) => setTypeFilter(e.target.value)}
                        className={`${reviewInput} w-full`}
                      >
                        <option value="all">All types</option>
                        <option value="medicine">Medicine</option>
                        <option value="equipment">Equipment</option>
                      </select>
                      <select
                        aria-label="Problem category filter"
                        value={categoryFilter}
                        onChange={(e) => setCategoryFilter(e.target.value)}
                        className={`${reviewInput} w-full`}
                      >
                        <option value="all">All problems</option>
                        {[
                          ...new Set(
                            (data.issues ?? []).filter((i) => i.state === 'open').map((i) => i.category),
                          ),
                        ].map((category) => (
                          <option key={category} value={category}>
                            {problemLabels[category] ?? category}
                          </option>
                        ))}
                      </select>
                      {[stateFilter, typeFilter, categoryFilter].some((filter) => filter !== 'all') && (
                        <button
                          type="button"
                          className="text-xs text-[#1B4E8A]"
                          onClick={() => {
                            setStateFilter('all');
                            setTypeFilter('all');
                            setCategoryFilter('all');
                          }}
                        >
                          Clear filters
                        </button>
                      )}
                    </div>
                  </details>
                  {(showRemoved || (data.reviewCounts?.removed ?? 0) > 0) && (
                    <button
                      type="button"
                      className="shrink-0 px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs hover:bg-gray-50"
                      aria-pressed={showRemoved}
                      onClick={() => setShowRemoved(!showRemoved)}
                    >
                      {showRemoved ? 'Active items' : `Removed items (${data.reviewCounts?.removed ?? 0})`}
                    </button>
                  )}
                </div>
                {selectedItems.length > 0 && (
                  <div
                    role="toolbar"
                    aria-label="Selected item actions"
                    className="flex flex-wrap gap-2 items-center bg-slate-50 border border-slate-200 rounded-lg p-3"
                  >
                    <span className="text-sm font-medium mr-2">{selectedItems.length} items selected</span>
                    {showRemoved ? (
                      <button
                        type="button"
                        className={reviewButton}
                        disabled={itemMutationPending}
                        onClick={() =>
                          void operations.preview({
                            action: 'restore',
                            itemIds: selectedItems.map((i) => i.id),
                          })
                        }
                      >
                        Restore selected
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          className={reviewButton}
                          disabled={itemMutationPending}
                          onClick={() => setShowBulkEdit(!showBulkEdit)}
                        >
                          Edit field
                        </button>
                        <button
                          type="button"
                          className={reviewButton}
                          disabled={itemMutationPending}
                          onClick={() =>
                            void operations.preview({
                              action: 'remove',
                              itemIds: selectedItems.map((i) => i.id),
                            })
                          }
                        >
                          Remove selected
                        </button>
                        <details className="relative">
                          <summary className={`${reviewButton} list-none cursor-pointer`}>
                            More actions
                          </summary>
                          <div className="absolute left-0 top-full mt-2 z-20 w-72 bg-white border border-gray-200 rounded-lg shadow-lg p-3">
                            <p className="text-xs text-gray-500 mb-2">
                              Optional: record an additional human check for items that are already ready.
                            </p>
                            <button
                              type="button"
                              className={reviewButton}
                              disabled={
                                itemMutationPending ||
                                selectedItems.some((item) => !isReady(item)) ||
                                selectedItems.every((item) => item.verificationSource === 'human')
                              }
                              onClick={(event) => {
                                const menu = event.currentTarget.closest('details');
                                if (menu) menu.open = false;
                                void operations.preview({
                                  action: 'verify',
                                  itemIds: selectedItems.map((item) => item.id),
                                });
                              }}
                            >
                              Record human verification
                            </button>
                          </div>
                        </details>
                      </>
                    )}
                    <button type="button" className={reviewButton} onClick={() => setSelected(new Set())}>
                      Clear selection
                    </button>
                  </div>
                )}
                <BulkEdit
                  selected={selectedItems}
                  hidden={!showBulkEdit || showRemoved || !selectedItems.length}
                  operations={operations}
                />
              </div>
            )}

            <div
              role="region"
              aria-label="Request items table"
              tabIndex={0}
              className="review-items-table bg-white rounded-xl border border-gray-200 max-w-full overflow-auto overscroll-contain focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"
            >
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    {structuredReview && (
                      <th className="sticky top-0 z-10 bg-gray-50 pl-4 pr-0 py-3 w-10">
                        <ReviewCheckbox
                          label="Select all filtered items"
                          checked={displayItems.length > 0 && displayItems.every((i) => selected.has(i.id))}
                          mixed={
                            displayItems.some((i) => selected.has(i.id)) &&
                            !displayItems.every((i) => selected.has(i.id))
                          }
                          disabled={itemMutationPending}
                          onChange={(checked) =>
                            setSelected(checked ? new Set(displayItems.map((i) => i.id)) : new Set())
                          }
                        />
                      </th>
                    )}
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
                      ...(!structuredReview ? [{ key: null, label: 'Confidence' }] : []),
                      { key: null, label: 'Review status' },
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
                            onSave={(next) => renameColumn(header.key!, next)}
                          />
                        ) : (
                          header.label
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {displayItems.length === 0 && (
                    <tr>
                      <td colSpan={columnCount} className="px-6 py-12 text-center">
                        <PenLine size={24} className="mx-auto mb-3 text-gray-300" />
                        <div className="text-sm text-gray-500">
                          {showRemoved
                            ? 'No removed items match these filters.'
                            : items.length
                              ? 'No items match these filters.'
                              : 'No items yet. Add your first item below.'}
                        </div>
                      </td>
                    </tr>
                  )}
                  {displayItems.map((item, index) => {
                    const status = STATUS_CFG[item.status];
                    const presentation = reviewPresentation(item, data.issues);
                    const priority = PRIORITY_CFG[item.priority];
                    const sharedCheck = (data.issues ?? []).find(
                      (issue) =>
                        issue.scope === 'table' && issue.state === 'open' && issue.itemIds?.includes(item.id),
                    );
                    const individualIssues = (data.issues ?? []).filter(
                      (issue) => issue.itemId === item.id && issue.state === 'open',
                    );
                    const blocked =
                      !showRemoved &&
                      (structuredReview ? individualIssues.length > 0 : needsManualReview(item));
                    const isExpanded = expandedItems.has(item.id);
                    const missingName = item.status === 'missing' || !item.name;

                    const mainRow = (
                      <tr
                        key={item.id}
                        className={`border-b border-gray-100 transition-colors ${
                          selected.has(item.id)
                            ? 'bg-slate-50 hover:bg-slate-100'
                            : blocked
                              ? 'bg-amber-50 hover:bg-amber-100/60'
                              : item.status === 'needs_review' && !sharedCheck
                                ? 'bg-amber-50/30 hover:bg-amber-50/60'
                                : 'hover:bg-gray-50/60'
                        }`}
                        style={blocked ? { boxShadow: 'inset 3px 0 0 #F59E0B' } : undefined}
                      >
                        {structuredReview && (
                          <td className="pl-4 pr-0 py-3">
                            <ReviewCheckbox
                              label={`Select ${item.name}`}
                              checked={selected.has(item.id)}
                              disabled={itemMutationPending}
                              onChange={(checked) =>
                                setSelected((previous) => toggleSelection(previous, item.id, checked))
                              }
                            />
                          </td>
                        )}
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
                        <td className="px-4 py-3 min-w-56 max-w-sm">
                          <button
                            onClick={() => {
                              if (!showRemoved) openEdit(item);
                            }}
                            className={`text-left transition-colors hover:underline ${
                              missingName ? 'text-gray-400 italic' : 'text-gray-900 hover:text-[#1B4E8A]'
                            }`}
                            style={{ fontWeight: missingName ? 400 : 500, fontSize: 14 }}
                          >
                            {missingName ? '- Missing -' : item.name}
                          </button>
                          {!!item.reviewReasons?.length && (
                            <ul className="text-xs text-amber-700 mt-1">
                              {item.reviewReasons
                                .filter((reason) => reason !== sharedCheck?.message)
                                .map((reason, i) => (
                                  <li key={i}>{reason}</li>
                                ))}
                            </ul>
                          )}
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
                              <span className="text-sm text-gray-500">
                                {item.unit}
                                {/* AI inferences stay in item details (the status already says
                                  "AI checked"); a plain default has no other signal, so it's
                                  marked here. */}
                                {unitSourceTag(item) === 'default' && (
                                  <span className="ml-1.5 text-[11px] text-gray-400 italic">default</span>
                                )}
                              </span>
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
                            <span
                              className={`text-xs ${item.notes ? 'text-gray-500' : 'text-gray-300 italic'}`}
                            >
                              {item.notes || '-'}
                            </span>
                          </td>
                        )}
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex px-2 py-0.5 rounded-full text-xs ${priority.bg} ${priority.color}`}
                            style={{ fontWeight: 600 }}
                          >
                            {priority.label}
                          </span>
                        </td>
                        {!structuredReview && (
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
                        )}
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs whitespace-nowrap ${showRemoved ? 'bg-gray-100 text-gray-500' : structuredReview ? (presentation.tone === 'ready' ? 'bg-teal-50 text-teal-700' : 'bg-amber-50 text-amber-800') : `${status.bg} ${status.color}`}`}
                            style={{ fontWeight: 500 }}
                            title={showRemoved ? 'Excluded from matching' : presentation.description}
                          >
                            {structuredReview ? (
                              presentation.tone === 'ready' ? (
                                <CheckCircle2 size={12} />
                              ) : (
                                <AlertCircle size={12} />
                              )
                            ) : (
                              status.icon
                            )}{' '}
                            {showRemoved
                              ? 'Removed'
                              : structuredReview
                                ? presentation.label
                                : sharedCheck && !blocked
                                  ? 'Shared column check'
                                  : item.verificationSource === 'ai' && item.status === 'verified'
                                    ? 'AI checked'
                                    : item.status === 'verified' && item.verificationSource !== 'human'
                                      ? 'Ready'
                                      : status.label}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {showRemoved ? (
                            <button
                              type="button"
                              className={reviewButton}
                              disabled={itemMutationPending}
                              onClick={() =>
                                void operations.preview({ action: 'restore', itemIds: [item.id] })
                              }
                            >
                              Restore
                            </button>
                          ) : (
                            <div className="flex items-center gap-1.5">
                              {blocked ? (
                                <button
                                  onClick={() => {
                                    if (!showRemoved) openEdit(item);
                                  }}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-amber-500 text-white hover:bg-amber-600 transition-colors shadow-sm"
                                  style={{ fontWeight: 700 }}
                                >
                                  <AlertTriangle size={12} />
                                  Review Required
                                </button>
                              ) : (
                                <>
                                  <button
                                    onClick={() => {
                                      if (!showRemoved) openEdit(item);
                                    }}
                                    className="flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
                                    style={{ fontWeight: 500 }}
                                  >
                                    <Edit2 size={11} /> Edit
                                  </button>
                                  {!structuredReview && !sharedCheck && item.status === 'needs_review' && (
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
                              {(item.manual || structuredReview) && (
                                <button
                                  onClick={() => void removeItem(item.id)}
                                  disabled={itemMutationPending || isAddingColumn}
                                  aria-label={`Remove ${item.name}`}
                                  title="Remove item from request"
                                  className="p-1 rounded text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors disabled:opacity-40"
                                >
                                  <X size={14} />
                                </button>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );

                    const detailRow =
                      attributeColumns.length > 0 && isExpanded ? (
                        <tr key={`${item.id}-details`} className="border-b border-gray-100 bg-gray-50/60">
                          <td colSpan={columnCount} className="px-12 py-3">
                            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 max-w-3xl">
                              {attributeColumns.map((label) => (
                                <Fragment key={label}>
                                  {/* label (not the renamed text) is always the lookup key into
                                    item.attributes and the rename endpoint's columnKey - only
                                    what's displayed changes when the user renames it. */}
                                  <dt className="text-xs text-gray-500" style={{ fontWeight: 600 }}>
                                    <EditableLabel
                                      value={columnLabel(label, label)}
                                      onSave={(next) => renameColumn(label, next)}
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
              <div className="text-sm text-gray-500">
                {allVerified
                  ? 'All items have passed review. You can start matching; no extra row verification is needed.'
                  : `${data.tasks?.length ?? blockedItems.length} review tasks remain. Resolve shared checks in guided review.`}
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
        </div>
      </div>

      {editingItem && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6"
          onClick={(event) => {
            if (event.target === event.currentTarget && !isNewItem && !isSavingItem) setEditingItem(null);
          }}
        >
          <form
            ref={itemDialog}
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void saveEdit();
            }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="item-dialog-title"
            aria-describedby={showItemValidation && !canSave ? 'item-validation-summary' : undefined}
            tabIndex={-1}
            className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col overflow-hidden outline-none"
          >
            <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between shrink-0">
              <div>
                <h3 id="item-dialog-title" className="text-gray-900">
                  {isNewItem
                    ? 'Add Item Manually'
                    : editingItem.manual
                      ? 'Edit Manual Item'
                      : editingItem.status === 'missing'
                        ? 'Complete Missing Information'
                        : 'Edit Extracted Item'}
                </h3>
                <p className="text-gray-500 text-sm mt-0.5">
                  {editingItem.manual
                    ? 'Not linked to a source document'
                    : `Row #${sourceReferences[editingItem.id]?.row ?? editingItem.id} in source document`}
                </p>
              </div>
              {!isNewItem && (
                <button
                  type="button"
                  disabled={isSavingItem}
                  aria-label="Close item dialog"
                  onClick={() => setEditingItem(null)}
                  className="p-2 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors"
                >
                  <X size={18} />
                </button>
              )}
            </div>

            <div className="px-6 py-5 min-h-0 overflow-y-auto overscroll-contain">
              {itemError && (
                <div className="mb-4">
                  <ErrorPanel message={itemError} />
                </div>
              )}
              <SourceReferencePanel item={editingItem} reference={sourceReferences[editingItem.id]} />
              {structuredReview &&
                (data.issues ?? [])
                  .filter(
                    (issue) => issue.itemId === editingItem.id && issue.state === 'open' && issue.canAccept,
                  )
                  .map((issue) => (
                    <div key={issue.id} className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                      <p className="text-xs text-amber-900 mb-2">{issue.message}</p>
                      <button
                        type="button"
                        className={reviewButton}
                        disabled={itemMutationPending}
                        onClick={() =>
                          void operations.preview({
                            action: 'accept',
                            itemIds: [editingItem.id],
                            issueIds: [issue.id],
                          })
                        }
                      >
                        I inspected the source — accept current value
                      </button>
                    </div>
                  ))}
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                      Item #
                    </label>
                    <input
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]"
                      value={editValues.itemNumber ?? ''}
                      onChange={(event) =>
                        setEditValues((values) => ({ ...values, itemNumber: event.target.value }))
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
                      onChange={(event) =>
                        setEditValues((values) => ({ ...values, shelfLife: event.target.value }))
                      }
                    />
                  </div>
                </div>
                <div>
                  <label
                    htmlFor="item-name"
                    className={`block text-xs mb-1 ${nameInvalid ? 'text-red-600' : 'text-gray-500'}`}
                    style={{ fontWeight: 600 }}
                  >
                    Item Name (required)
                  </label>
                  <input
                    id="item-name"
                    className={`w-full border rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ${nameInvalid ? 'border-red-500 bg-red-50 focus:ring-red-500/20 focus:border-red-500' : 'border-gray-300 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]'}`}
                    aria-label="Item Name"
                    aria-required="true"
                    aria-invalid={nameInvalid}
                    aria-describedby={nameInvalid ? 'item-name-error' : undefined}
                    autoFocus={editingItem.manual}
                    placeholder={editingItem.manual ? 'e.g. Ceftriaxone 1g Powder for Injection' : ''}
                    value={editValues.name ?? ''}
                    onChange={(event) => setEditValues((values) => ({ ...values, name: event.target.value }))}
                  />
                  {nameInvalid && (
                    <p id="item-name-error" className="mt-1 text-xs text-red-600">
                      Enter an item name.
                    </p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="item-quantity"
                      className={`block text-xs mb-1 ${quantityInvalid ? 'text-red-600' : 'text-gray-500'}`}
                      style={{ fontWeight: 600 }}
                    >
                      Quantity (required)
                    </label>
                    <input
                      type="number"
                      id="item-quantity"
                      aria-label="Quantity"
                      aria-required="true"
                      aria-invalid={quantityInvalid}
                      aria-describedby={quantityInvalid ? 'item-quantity-error' : undefined}
                      min={1}
                      step={1}
                      className={`w-full border rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ${quantityInvalid ? 'border-red-500 bg-red-50 focus:ring-red-500/20 focus:border-red-500' : 'border-gray-300 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]'}`}
                      value={editValues.quantity ?? ''}
                      onChange={(event) =>
                        setEditValues((values) => ({
                          ...values,
                          quantity: event.target.value ? Number(event.target.value) : null,
                        }))
                      }
                    />
                    {quantityInvalid && (
                      <p id="item-quantity-error" className="mt-1 text-xs text-red-600">
                        Enter a positive whole-number quantity.
                      </p>
                    )}
                  </div>
                  <div>
                    <label
                      htmlFor="item-unit"
                      className="block text-xs text-gray-500 mb-1"
                      style={{ fontWeight: 600 }}
                    >
                      Unit
                      {unitInferred && (
                        <span id="item-unit-inference" className="ml-2 text-gray-400 font-normal">
                          {editingItem && unitSourceTag(editingItem)}
                        </span>
                      )}
                    </label>
                    <input
                      id="item-unit"
                      aria-describedby={unitInferred ? 'item-unit-inference' : undefined}
                      className={`w-full border rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] ${unitInferred && editingItem && unitSourceTag(editingItem) !== 'default' ? 'border-amber-400 bg-amber-50' : 'border-gray-300 bg-white'}`}
                      value={editValues.unit ?? ''}
                      onChange={(event) =>
                        setEditValues((values) => ({ ...values, unit: event.target.value }))
                      }
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
                    onChange={(event) =>
                      setEditValues((values) => ({ ...values, notes: event.target.value }))
                    }
                  />
                </div>
                <div>
                  <label
                    htmlFor="item-type"
                    className={`block text-xs mb-1 ${typeInvalid ? 'text-red-600' : 'text-gray-500'}`}
                    style={{ fontWeight: 600 }}
                  >
                    Product type (required)
                    {typeInferred && (
                      <span id="item-type-inference" className="ml-2 text-amber-700 font-normal">
                        AI inferred
                      </span>
                    )}
                  </label>
                  <select
                    id="item-type"
                    aria-label="Product type"
                    aria-required="true"
                    aria-invalid={typeInvalid}
                    aria-describedby={
                      typeInvalid ? 'item-type-error' : typeInferred ? 'item-type-inference' : undefined
                    }
                    className={`w-full border rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ${typeInvalid ? 'border-red-500 bg-red-50 focus:ring-red-500/20 focus:border-red-500' : `${typeInferred ? 'border-amber-400 bg-amber-50' : 'border-gray-300 bg-white'} focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]`}`}
                    value={editValues.domain ?? ''}
                    onChange={(event) =>
                      setEditValues((values) => ({
                        ...values,
                        domain: event.target.value as ExtractedItem['domain'],
                      }))
                    }
                  >
                    <option value="">Choose type</option>
                    <option value="medicine">Medicine</option>
                    <option value="equipment">Equipment</option>
                  </select>
                  {typeInvalid && (
                    <p id="item-type-error" className="mt-1 text-xs text-red-600">
                      Choose a product type.
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1" style={{ fontWeight: 600 }}>
                    Priority
                  </label>
                  <select
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A] bg-white"
                    value={editValues.priority ?? editingItem.priority}
                    onChange={(event) =>
                      setEditValues((values) => ({ ...values, priority: event.target.value as Priority }))
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

            <div className="px-6 py-4 border-t border-gray-200 shrink-0">
              {showItemValidation && !canSave && (
                <p id="item-validation-summary" role="alert" className="mb-3 text-sm text-red-700">
                  Complete required fields: {invalidFieldLabels.join(', ')}.
                </p>
              )}
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  disabled={isSavingItem}
                  onClick={() => setEditingItem(null)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                  style={{ fontWeight: 500 }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSavingItem}
                  className="px-5 py-2 bg-[#1B4E8A] text-white rounded-lg text-sm hover:bg-[#163d6d] transition-colors disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed"
                  style={{ fontWeight: 600 }}
                >
                  {isSavingItem
                    ? 'Saving…'
                    : isNewItem
                      ? 'Add Item'
                      : structuredReview
                        ? 'Preview changes'
                        : 'Save & Mark Verified'}
                </button>
              </div>
            </div>
          </form>
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
              Once you proceed, the item list will be locked. The matching step requires significant compute
              and cannot be undone without starting a new request.
            </p>
            <div className="mt-5 bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div className="text-xs text-gray-500" style={{ fontWeight: 600 }}>
                Summary
              </div>
              <div className="text-xs text-gray-700 mt-1">
                {items.length} items · {verified} verified
                {manualCount > 0 && ` · ${manualCount} manual`} · Partner: {partnerDetails.partner || '—'}
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

function SourceReferencePanel({ item, reference }: { item: ExtractedItem; reference?: SourceReference }) {
  const isMissing = item.status === 'missing';

  if (item.manual) {
    return (
      <div className="border border-dashed border-slate-300 bg-slate-50 rounded-xl p-4 mb-5 flex items-start gap-2.5">
        <PenLine size={14} className="text-slate-500 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-slate-600 leading-relaxed">
          <span className="font-bold">Manual entry.</span> This item is added by you and will be marked as
          verified. Name, a positive whole-number quantity and product type are required.
        </div>
      </div>
    );
  }

  return (
    <div
      className={`border rounded-xl p-4 mb-5 ${isMissing ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <BookOpen size={14} className={isMissing ? 'text-red-500' : 'text-amber-600'} />
        <span
          className={`text-xs ${isMissing ? 'text-red-800' : 'text-amber-800'}`}
          style={{ fontWeight: 700 }}
        >
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
      {!!item.reviewReasons?.length && (
        <ul className="mt-3 text-xs text-amber-800 list-disc pl-4">
          {item.reviewReasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      )}
      <div
        className={`flex items-center gap-1.5 mt-2 text-xs ${isMissing ? 'text-red-600' : 'text-amber-600'}`}
      >
        <Info size={11} />
        {isMissing
          ? 'Item name extracted. Quantity could not be read. Please enter it manually.'
          : item.verificationSource === 'ai'
            ? `AI checked against the source${item.confidence == null ? '' : ` · ${item.confidence}% confidence`}`
            : item.confidence == null
              ? 'Check against the original source'
              : `Extracted with ${item.confidence}% confidence`}
      </div>
    </div>
  );
}

function partnerLabel(key: keyof Pick<PartnerDetails, 'partner' | 'region' | 'requestId' | 'contact'>) {
  return { partner: 'Partner', region: 'Region', requestId: 'Request ID', contact: 'Contact' }[key];
}
