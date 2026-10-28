import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, CheckCircle2, FileText, ListChecks, SkipForward, X } from 'lucide-react';
import type { ExtractedItem, ItemUpdate, ReviewResponse } from '../../api/types';
import type { ReviewOperations } from '../../features/review/use-review-operations';

export const reviewInput =
  'border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]';
export const reviewButton =
  'px-3 py-2 rounded-lg border border-gray-300 text-sm hover:bg-gray-50 disabled:opacity-50';
const primary = 'px-4 py-2 rounded-lg text-sm bg-[#1B4E8A] text-white hover:bg-[#163d6d] disabled:opacity-50';
export type ReviewView = 'overview' | 'guided' | 'all';
export const problemLabels: Record<string, string> = {
  type: 'Product type',
  quantity: 'Missing or invalid quantity',
  totals: 'Conflicting quantities',
  unit: 'Units and packaging',
  description: 'Product description',
  source: 'Source extraction',
  other: 'Other uncertainty',
};
const fieldLabels: Record<string, string> = {
  domain: 'Product type',
  quantity: 'Quantity',
  unit: 'Unit',
  priority: 'Priority',
  shelf_life: 'Shelf life',
  notes: 'Notes',
  name: 'Item name',
  item_number: 'Item number',
  removed_at: 'Request state',
  verification_source: 'Verification',
};

function previewValue(field: string, value: unknown) {
  if (field === 'removed_at') return value ? 'Removed' : 'Active';
  if (field === 'verification_source')
    return value === 'human' ? 'Human verified' : value === 'ai' ? 'AI checked' : 'Ready';
  return value === null || value === undefined || value === '' ? 'Empty' : String(value);
}

export function ReviewCheckbox({
  checked,
  mixed = false,
  label,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  mixed?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = mixed;
  }, [mixed]);
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={(event) => onChange(event.target.checked)}
      className="h-4 w-4 rounded border-gray-300 accent-slate-600 cursor-pointer focus-visible:outline-2 focus-visible:outline-[#1B4E8A] disabled:opacity-50"
    />
  );
}

export function ReviewDialog({
  title,
  onClose,
  children,
  busy = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const pending = useRef(busy);
  pending.current = busy;
  useEffect(() => {
    const previous = document.activeElement;
    const root = ref.current;
    root?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (!pending.current) close.current();
      }
      if (event.key !== 'Tab' || !root) return;
      const controls = Array.from(
        root.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
        ),
      );
      const first = controls[0],
        last = controls.at(-1);
      if (!first) {
        event.preventDefault();
        return;
      }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === root)) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === root)) {
        event.preventDefault();
        first.focus();
      }
    };
    root?.addEventListener('keydown', trap);
    return () => {
      root?.removeEventListener('keydown', trap);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return (
    <div
      className="fixed inset-0 z-[70] bg-black/40 flex items-center justify-center p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-auto outline-none"
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-200">
          <h2 className="text-lg text-gray-900">{title}</h2>
          <button
            type="button"
            aria-label="Close dialog"
            disabled={busy}
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100"
          >
            <X size={18} />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}

export function ReviewOverview({
  data,
  onStart,
  onAll,
}: {
  data: ReviewResponse;
  onStart: () => void;
  onAll: () => void;
}) {
  const counts = data.reviewCounts;
  const tasks = data.tasks ?? [];
  return (
    <section className="bg-white rounded-xl border border-gray-200 p-6 mb-4" aria-label="Review overview">
      <div className="flex items-center gap-2 text-[#1B4E8A] mb-3">
        <ListChecks size={20} />
        <h2 className="text-lg text-gray-900">Review related problems together</h2>
      </div>
      <p className="text-sm text-gray-500 mb-5">
        We’ve grouped related problems so you can review several items together.
      </p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        {[
          [counts?.active ?? data.items.length, 'Active items'],
          [counts?.ready ?? 0, 'Ready'],
          [counts?.affected ?? 0, 'Need attention'],
          [tasks.length, 'Review tasks'],
        ].map(([value, label]) => (
          <div key={label} className="rounded-lg border border-gray-200 p-4">
            <div className="text-2xl font-semibold text-gray-900">{value}</div>
            <div className="text-xs text-gray-500 mt-1">{label}</div>
          </div>
        ))}
      </div>
      <div className="divide-y divide-gray-100 mb-5">
        {tasks.map((task) => (
          <div key={task.id} className="flex justify-between gap-4 py-2 text-sm">
            <span className="text-gray-700">
              {task.title}
              {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
            </span>
            <span className="text-gray-500">
              {task.itemIds.length || 'Document'} {task.itemIds.length ? 'items' : ''}
            </span>
          </div>
        ))}
      </div>
      {!tasks.length && (
        <p className="text-sm text-green-700 mb-4">
          No open review tasks. Check the complete list before matching.
        </p>
      )}
      <div className="flex gap-3">
        <button type="button" className={primary} onClick={tasks.length ? onStart : onAll}>
          {tasks.length ? 'Start guided review' : 'Review all items'}
        </button>
        <button type="button" className={reviewButton} onClick={onAll}>
          View all items
        </button>
      </div>
    </section>
  );
}

function readProgress(requestId: string): { current: string | null; deferred: string[] } {
  try {
    return (
      JSON.parse(sessionStorage.getItem(`review-progress:${requestId}`) ?? 'null') ?? {
        current: null,
        deferred: [],
      }
    );
  } catch {
    return { current: null, deferred: [] };
  }
}

export function GuidedReview({
  data,
  hidden,
  operations,
  onEdit,
  onAll,
}: {
  data: ReviewResponse;
  hidden: boolean;
  operations: ReviewOperations;
  onEdit: (item: ExtractedItem) => void;
  onAll: () => void;
}) {
  const [progress, setProgress] = useState(() => readProgress(data.requestId));
  const [drafts, setDrafts] = useState<
    Record<string, { value: string; selected: number[]; inspected: number[] }>
  >({});
  const tasks = data.tasks ?? [];
  const task =
    tasks.find((t) => t.id === progress.current) ??
    tasks.find((t) => !progress.deferred.includes(t.id)) ??
    tasks[0];
  useEffect(() => {
    try {
      sessionStorage.setItem(`review-progress:${data.requestId}`, JSON.stringify(progress));
    } catch {
      /* private browsing */
    }
  }, [progress, data.requestId]);
  if (!task)
    return (
      <section hidden={hidden} className="rounded-xl border border-gray-200 bg-white p-8 mb-4 text-center">
        <CheckCircle2 className="mx-auto text-[#0E9E8F] mb-3" size={28} />
        <h2>All review tasks resolved</h2>
        <p className="text-sm text-gray-500 mt-2 mb-5">Check the complete list before starting matching.</p>
        <button type="button" onClick={onAll} className={primary}>
          Review all items
        </button>
      </section>
    );
  const draft = drafts[task.id] ?? {
    value: task.suggestedValue ?? '',
    selected: task.itemIds,
    inspected: [],
  };
  const update = (patch: Partial<typeof draft>) =>
    setDrafts((previous) => ({ ...previous, [task.id]: { ...draft, ...patch } }));
  const selected = draft.selected.filter((id) => task.itemIds.includes(id));
  const members = data.items.filter((item) => task.itemIds.includes(item.id));
  const issues = (data.issues ?? []).filter((issue) => task.issueIds.includes(issue.id));
  const selectedIssues = issues.filter((i) => i.itemId === null || selected.includes(i.itemId));
  const canAccept =
    task.canAccept && selectedIssues.every((i) => i.itemId === null || draft.inspected.includes(i.itemId));
  const field =
    task.category === 'type'
      ? 'domain'
      : task.category === 'quantity' || task.category === 'totals'
        ? 'quantity'
        : task.category === 'unit'
          ? 'unit'
          : null;
  const makeChange = () => {
    if (!field) return;
    void operations.preview({
      action: 'edit',
      itemIds: selected,
      changes: { [field]: field === 'quantity' ? Number(draft.value) : draft.value },
    });
  };
  return (
    <section hidden={hidden} aria-label="Guided review" className="mb-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <span className="text-sm text-gray-500">
          {tasks.length} tasks remaining · {data.reviewCounts?.affected ?? 0} items need attention
        </span>
        <select
          aria-label="Review task"
          className={reviewInput}
          value={task.id}
          onChange={(e) => setProgress((p) => ({ ...p, current: e.target.value }))}
        >
          {tasks.map((t) => (
            <option key={t.id} value={t.id}>
              {progress.deferred.includes(t.id) ? 'Later · ' : ''}
              {t.title}
              {t.suggestedValue ? ` · ${t.suggestedValue}` : ''} ({t.itemIds.length || 'document'})
            </option>
          ))}
        </select>
      </div>
      <div
        key={task.id}
        className="review-task-in bg-white border border-gray-200 rounded-xl overflow-hidden"
      >
        <div className="p-5 border-b border-gray-200">
          <h2 className="text-lg">
            {task.title}
            {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {issues[0]?.message} Resolve this problem for selected items, or edit exceptions individually.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="p-3 w-10">
                  <ReviewCheckbox
                    label="Select all task items"
                    checked={selected.length === members.length && !!members.length}
                    mixed={!!selected.length && selected.length < members.length}
                    onChange={(checked) => update({ selected: checked ? task.itemIds : [] })}
                  />
                </th>
                <th className="p-3 text-left">Item</th>
                <th className="p-3 text-left">Current value</th>
                <th className="p-3 text-left">Source evidence</th>
                <th className="p-3" />
              </tr>
            </thead>
            <tbody>
              {members.map((item) => {
                const issue = issues.find((i) => i.itemId === item.id);
                const reference = data.sourceReferences.find((r) => r.itemId === item.id);
                return (
                  <tr key={item.id} className="border-t border-gray-100">
                    <td className="p-3">
                      <ReviewCheckbox
                        label={`Select ${item.name}`}
                        checked={selected.includes(item.id)}
                        onChange={(checked) =>
                          update({
                            selected: checked
                              ? [...selected, item.id]
                              : selected.filter((id) => id !== item.id),
                          })
                        }
                      />
                    </td>
                    <td className="p-3 min-w-44 font-medium">{item.name}</td>
                    <td className="p-3">
                      {task.category === 'type'
                        ? (item.domain ?? 'Not chosen')
                        : task.category === 'unit'
                          ? item.unit || '—'
                          : (item.quantity ?? 'Missing')}
                      {task.category === 'totals' && (
                        <div className="text-xs text-gray-500 mt-1">
                          Requested: {issue?.requestedTotal ?? '—'}
                          <br />
                          {issue?.packs ?? '—'} × {issue?.unitsPerPack ?? '—'} ={' '}
                          {issue?.calculatedTotal ?? '—'}
                        </div>
                      )}
                    </td>
                    <td className="p-3 min-w-48 max-w-sm">
                      <details
                        onToggle={(e) => {
                          if (e.currentTarget.open && !draft.inspected.includes(item.id))
                            update({ inspected: [...draft.inspected, item.id] });
                        }}
                      >
                        <summary className="cursor-pointer text-[#1B4E8A]">
                          Inspect source · row {reference?.row ?? '—'}
                        </summary>
                        <p className="mt-2 p-3 rounded-lg bg-amber-50 text-xs text-amber-900 whitespace-pre-wrap">
                          {reference?.excerpt ??
                            issue?.evidence ??
                            'No source reference available. Check the original document.'}
                        </p>
                      </details>
                    </td>
                    <td className="p-3">
                      <button
                        type="button"
                        className={reviewButton}
                        disabled={operations.busy}
                        onClick={() => onEdit(item)}
                      >
                        Edit individually
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!members.length && (
          <p className="p-5 text-sm text-gray-600">
            {issues[0]?.evidence} Inspect the original document and add missed items from the full table.
          </p>
        )}
        <div className="p-5 border-t border-gray-200 space-y-3">
          {field && (
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-sm text-gray-600" htmlFor={`task-value-${task.id}`}>
                {task.category === 'totals' ? 'Or set an explicit quantity' : 'Set for selected items'}
              </label>
              {field === 'domain' ? (
                <select
                  id={`task-value-${task.id}`}
                  className={reviewInput}
                  value={draft.value}
                  onChange={(e) => update({ value: e.target.value })}
                >
                  <option value="">Choose type</option>
                  <option value="medicine">Medicine</option>
                  <option value="equipment">Equipment</option>
                </select>
              ) : (
                <input
                  id={`task-value-${task.id}`}
                  className={reviewInput}
                  type={field === 'quantity' ? 'number' : 'text'}
                  min={1}
                  step={1}
                  value={draft.value}
                  onChange={(e) => update({ value: e.target.value })}
                />
              )}
              <button
                type="button"
                className={primary}
                disabled={
                  operations.busy ||
                  !selected.length ||
                  !draft.value ||
                  (field === 'quantity' &&
                    (!Number.isInteger(Number(draft.value)) || Number(draft.value) <= 0))
                }
                onClick={makeChange}
              >
                Preview for {selected.length} items
              </button>
              {field === 'unit' && <span className="text-xs text-gray-500">Quantities stay unchanged.</span>}
            </div>
          )}
          {task.category === 'totals' && (
            <div className="flex gap-2 flex-wrap">
              {(['requested_total', 'pack_calculation'] as const).map((rule) => (
                <button
                  key={rule}
                  type="button"
                  className={reviewButton}
                  disabled={
                    operations.busy ||
                    !selected.length ||
                    !selectedIssues.every(
                      (i) => (rule === 'requested_total' ? i.requestedTotal : i.calculatedTotal) != null,
                    )
                  }
                  onClick={() =>
                    void operations.preview({ action: 'quantity_rule', itemIds: selected, rule })
                  }
                >
                  {rule === 'requested_total'
                    ? 'Use each row’s requested total'
                    : 'Use each row’s pack calculation'}
                </button>
              ))}
            </div>
          )}
          <div className="flex justify-between items-center gap-3 flex-wrap">
            {task.canAccept ? (
              <button
                type="button"
                className={reviewButton}
                disabled={operations.busy || !canAccept || !selectedIssues.length}
                onClick={() =>
                  void operations.preview({
                    action: 'accept',
                    itemIds: selected,
                    issueIds: selectedIssues.map((i) => i.id),
                  })
                }
              >
                {canAccept
                  ? 'Accept current values after inspection'
                  : 'Inspect each selected source to accept values'}
              </button>
            ) : (
              <span className="text-xs text-gray-500">Missing required values must be corrected.</span>
            )}
            <button
              type="button"
              className={`${reviewButton} inline-flex items-center gap-2`}
              onClick={() =>
                setProgress((p) => ({
                  current:
                    tasks.find((t) => t.id !== task.id && !p.deferred.includes(t.id))?.id ??
                    tasks.find((t) => t.id !== task.id)?.id ??
                    task.id,
                  deferred: [...new Set([...p.deferred, task.id])],
                }))
              }
            >
              <SkipForward size={14} /> Review later
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

export function OperationPreview({ operations }: { operations: ReviewOperations }) {
  const pending = operations.pending;
  if (!pending) return null;
  const { preview, operation } = pending;
  return (
    <ReviewDialog
      title={operation.action === 'remove' ? `Remove ${operation.itemIds.length} items?` : 'Review changes'}
      busy={operations.busy}
      onClose={() => operations.setPending(null)}
    >
      {operations.error && (
        <p role="alert" className="p-3 mb-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {operations.error}
        </p>
      )}
      {operation.action === 'remove' && (
        <p className="text-sm text-gray-600 mb-4">
          These items will be removed from this request. You can restore them from Removed items.
        </p>
      )}
      {operation.action === 'accept' && (
        <p className="text-sm text-gray-600 mb-4">
          Record your decision to keep these values after inspecting the source. Other problems remain open.
        </p>
      )}
      {operation.action === 'quantity_rule' && (
        <p className="text-sm text-gray-600 mb-4">
          {operation.rule === 'requested_total'
            ? 'Use each row’s requested total.'
            : 'Use each row’s pack calculation.'}{' '}
          This records your interpretation of the conflicting source quantities.
        </p>
      )}
      <div className="max-h-80 overflow-auto divide-y divide-gray-100">
        {preview.changes.map((change) => (
          <div key={change.itemId} className="py-3">
            <div className="text-sm font-medium">{change.name}</div>
            {Object.entries(change.fields)
              .filter(([field]) => field !== 'verification_source' || operation.action === 'verify')
              .map(([field, value]) => (
                <p key={field} className="text-xs text-gray-500 mt-1">
                  {fieldLabels[field] ?? field}: {previewValue(field, value.before)} →{' '}
                  <span className="text-gray-900">{previewValue(field, value.after)}</span>
                </p>
              ))}
          </div>
        ))}
      </div>
      {!!preview.blockers.length && (
        <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          <p>{preview.blockers.length} selected items still have unresolved problems.</p>
          {preview.blockers.map((b) => (
            <p key={b.itemId} className="text-xs mt-1">
              Item #{b.itemId}: {b.message}
            </p>
          ))}
          {!!preview.eligibleItemIds.length && (
            <button
              type="button"
              className={`${reviewButton} mt-3`}
              onClick={() => void operations.preview({ ...operation, itemIds: preview.eligibleItemIds })}
            >
              Preview {preview.eligibleItemIds.length} eligible items only
            </button>
          )}
        </div>
      )}
      <div className="mt-5 flex justify-end gap-3">
        <button
          type="button"
          className={reviewButton}
          disabled={operations.busy}
          onClick={() => operations.setPending(null)}
        >
          Cancel
        </button>
        <button
          type="button"
          className={primary}
          disabled={operations.busy || !!preview.blockers.length}
          onClick={() => void operations.apply()}
        >
          {operations.busy ? 'Saving…' : operation.action === 'remove' ? 'Remove items' : 'Confirm changes'}
        </button>
      </div>
    </ReviewDialog>
  );
}

export function BulkEdit({
  selected,
  hidden,
  operations,
}: {
  selected: ExtractedItem[];
  hidden: boolean;
  operations: ReviewOperations;
}) {
  const [field, setField] = useState('domain');
  const [value, setValue] = useState('');
  const [clear, setClear] = useState(false);
  const optional = field === 'notes' || field === 'shelfLife';
  const currentValues = [
    ...new Set(selected.map((item) => String(item[field as keyof ExtractedItem] ?? ''))),
  ];
  const numericValid = field !== 'quantity' || (Number.isInteger(Number(value)) && Number(value) > 0);
  return (
    <div hidden={hidden} className="border border-gray-200 rounded-xl bg-white p-4 mt-3 mb-3">
      <h3 className="text-sm mb-3">Edit field for {selected.length} selected items</h3>
      <p className="text-xs text-gray-500 mb-3">
        Current values: {currentValues.length > 1 ? 'Mixed values' : currentValues[0] || 'Empty'}. Other
        fields remain unchanged.
      </p>
      <div className="flex items-center gap-3 flex-wrap">
        <select
          aria-label="Bulk field"
          className={reviewInput}
          value={field}
          onChange={(e) => {
            setField(e.target.value);
            setValue('');
            setClear(false);
          }}
        >
          {[
            ['domain', 'Type'],
            ['quantity', 'Quantity'],
            ['unit', 'Unit'],
            ['priority', 'Priority'],
            ['shelfLife', 'Shelf life'],
            ['notes', 'Notes'],
          ].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        {field === 'domain' || field === 'priority' ? (
          <select
            aria-label="New value"
            className={reviewInput}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            <option value="">Choose value</option>
            {(field === 'domain' ? ['medicine', 'equipment'] : ['critical', 'high', 'medium', 'low']).map(
              (v) => (
                <option key={v}>{v}</option>
              ),
            )}
          </select>
        ) : (
          <input
            aria-label="New value"
            className={reviewInput}
            disabled={clear}
            type={field === 'quantity' ? 'number' : 'text'}
            min={1}
            step={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        )}
        {optional && (
          <label className="text-sm text-gray-600 flex gap-2 items-center">
            <ReviewCheckbox checked={clear} label="Clear this optional field" onChange={setClear} /> Clear
            this field
          </label>
        )}
        <button
          type="button"
          className={primary}
          disabled={operations.busy || !selected.length || !numericValid || (!clear && !value.trim())}
          onClick={() =>
            void operations.preview({
              action: 'edit',
              itemIds: selected.map((i) => i.id),
              changes: { [field]: clear ? '' : field === 'quantity' ? Number(value) : value } as ItemUpdate,
            })
          }
        >
          Preview changes
        </button>
      </div>
      {field === 'unit' && (
        <p className="text-xs text-gray-500 mt-2">This changes the unit label. Quantities stay unchanged.</p>
      )}
    </div>
  );
}

export function ReviewToast({ operations }: { operations: ReviewOperations }) {
  if (!operations.toast) return null;
  return (
    <div
      role="status"
      className="review-toast fixed bottom-5 right-5 z-[60] rounded-xl bg-white border border-gray-200 shadow-lg px-4 py-3 flex gap-4 items-center text-sm"
    >
      <CheckCircle2 size={16} className="text-[#0E9E8F]" />
      <span>{operations.toast.message}</span>
      {operations.toast.operationId && (
        <button
          type="button"
          disabled={operations.busy}
          onClick={() => void operations.undo()}
          className="font-semibold text-[#1B4E8A]"
        >
          Undo
        </button>
      )}
      <button type="button" aria-label="Dismiss notification" onClick={() => operations.setToast(null)}>
        <X size={15} />
      </button>
    </div>
  );
}

export function ViewNavigation({ view, setView }: { view: ReviewView; setView: (view: ReviewView) => void }) {
  return (
    <nav aria-label="Review views" className="flex gap-2 mb-4 flex-wrap">
      {(
        [
          ['overview', 'Overview', FileText],
          ['guided', 'Guided review', ArrowRight],
          ['all', 'All items', ListChecks],
        ] as const
      ).map(([key, label, Icon]) => (
        <button
          key={key}
          type="button"
          aria-current={view === key ? 'page' : undefined}
          className={`${reviewButton} inline-flex items-center gap-2 ${view === key ? 'bg-slate-100 text-gray-900 font-semibold' : 'bg-white text-gray-500'}`}
          onClick={() => setView(key)}
        >
          <Icon size={14} />
          {label}
        </button>
      ))}
    </nav>
  );
}
