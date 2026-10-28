import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, CheckCircle2, FileText, ListChecks, SkipForward, X } from 'lucide-react';
import type { ExtractedItem, ItemUpdate, ReviewResponse } from '../../api/types';
import { nextTask, deferTask, taskHistory, type TaskProgress } from '../../features/review/task-queue';
import { TaskTimeline } from './TaskTimeline';
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

function readProgress(requestId: string): TaskProgress {
  try {
    return (
      JSON.parse(sessionStorage.getItem(`review-progress:v2:${requestId}`) ?? 'null') ?? {
        current: null,
        deferred: [],
        history: [],
      }
    );
  } catch {
    return { current: null, deferred: [], history: [] };
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
  const [progress, setProgress] = useState(() => {
    const saved = readProgress(data.requestId);
    return { ...saved, history: taskHistory(saved.history, data.tasks ?? []) };
  });
  const [drafts, setDrafts] = useState<
    Record<string, { value: string; selected: number[]; inspected: number[]; groupInspected?: boolean }>
  >({});
  const tasks = data.tasks ?? [];
  const target = nextTask(tasks, progress);
  const history = taskHistory(progress.history, tasks);
  const [display, setDisplay] = useState<{ task: typeof target; data: ReviewResponse }>({
    task: target,
    data,
  });
  const displayId = useRef(target?.id);
  const resolvedTransition = useRef(false);
  const [phase, setPhase] = useState<'hold' | 'in' | 'out' | 'idle'>('idle');
  useEffect(() => {
    try {
      sessionStorage.setItem(
        `review-progress:v2:${data.requestId}`,
        JSON.stringify({ ...progress, history }),
      );
    } catch {
      /* private browsing */
    }
  }, [progress, data]);
  useEffect(() => {
    const reduced =
      typeof window === 'undefined' ||
      !window.matchMedia ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (displayId.current === target?.id || hidden || reduced) {
      displayId.current = target?.id;
      setDisplay({ task: target, data });
      setPhase('idle');
      return;
    }
    // Match the prototype: acknowledge a resolved task, then slide out and in.
    // Skipping or jumping between open tasks has no success acknowledgement.
    const resolved = !!displayId.current && !tasks.some((task) => task.id === displayId.current);
    resolvedTransition.current = resolved;
    const hold = resolved ? 340 : 0;
    setPhase(resolved ? 'hold' : 'out');
    const acknowledge = setTimeout(() => setPhase('out'), hold);
    const leave = setTimeout(() => {
      displayId.current = target?.id;
      setDisplay({ task: target, data });
      setPhase('in');
    }, hold + 200);
    const enter = setTimeout(() => setPhase('idle'), hold + 430);
    return () => {
      clearTimeout(acknowledge);
      clearTimeout(leave);
      clearTimeout(enter);
    };
  }, [target?.id, data, hidden]);
  const task = display.task;
  const taskData = display.data;
  const timeline = (
    <TaskTimeline
      history={history}
      tasks={tasks}
      current={target?.id ?? null}
      deferred={progress.deferred}
      onSelect={(id) => setProgress((p) => ({ ...p, history, current: id }))}
    />
  );
  const skip = () => {
    if (task) setProgress((p) => deferTask(tasks, { ...p, history }, task.id));
  };
  if (!task)
    return (
      <section hidden={hidden} className="space-y-4 mb-4" aria-label="Guided review">
        {timeline}
        <div
          className={`bg-white border border-gray-200 rounded-xl p-8 text-center ${phase === 'in' ? 'review-task-in' : ''}`}
        >
          {tasks.length ? (
            <>
              <SkipForward size={28} className="mx-auto text-amber-500 mb-3" />
              <h2>Remaining tasks are set aside</h2>
              <p className="text-sm text-gray-500 mt-2 mb-5">
                {tasks.length} skipped tasks are still open. Nothing has been marked as resolved.
              </p>
              <button
                type="button"
                className={primary}
                onClick={() =>
                  setProgress((p) => ({ ...p, history, current: tasks[0]?.id ?? null, deferred: [] }))
                }
              >
                Review skipped tasks
              </button>
            </>
          ) : (
            <>
              <div className="review-pop mx-auto mb-4 w-14 h-14 rounded-full border border-teal-200 bg-teal-50 flex items-center justify-center">
                <CheckCircle2 size={28} className="text-[#0E9E8F]" />
              </div>
              <h2>All review tasks resolved</h2>
              <p className="text-sm text-gray-500 mt-2 mb-5">
                Check the complete list before starting matching.
              </p>
            </>
          )}
          <button type="button" className={`${reviewButton} ml-3`} onClick={onAll}>
            Review all items
          </button>
        </div>
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
  const members = taskData.items.filter((item) => task.itemIds.includes(item.id));
  const issues = (taskData.issues ?? []).filter((issue) => task.issueIds.includes(issue.id));
  const selectedIssues = issues.filter((i) => i.itemId === null || selected.includes(i.itemId));
  const canAccept =
    task.canAccept &&
    (!!draft.groupInspected ||
      selectedIssues.every((i) => i.itemId === null || draft.inspected.includes(i.itemId)));
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
    <section hidden={hidden} aria-label="Guided review" className="space-y-4 mb-4">
      {timeline}
      <div
        key={task.id}
        className={`${phase === 'out' ? 'review-task-out' : phase === 'in' ? 'review-task-in' : ''} relative bg-white border border-gray-200 rounded-xl overflow-hidden`}
        ref={(element) => element?.toggleAttribute('inert', phase === 'hold' || phase === 'out')}
        style={{ pointerEvents: phase === 'hold' || phase === 'out' ? 'none' : undefined }}
      >
        {(phase === 'hold' || phase === 'out') && resolvedTransition.current && (
          <div
            role="status"
            className="review-fade absolute inset-0 z-10 bg-white/95 flex flex-col items-center justify-center gap-3 p-6 text-teal-800"
          >
            <span className="review-pop w-14 h-14 rounded-full border border-teal-200 bg-teal-50 flex items-center justify-center">
              <CheckCircle2 size={28} />
            </span>
            <span className="text-base font-semibold">Task resolved</span>
            <span className="text-sm text-gray-500">Changes saved</span>
          </div>
        )}
        <div className="p-5 border-b border-gray-200">
          <h2 className="text-lg">
            {task.title}
            {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {issues[0]?.message}
            {issues[0]?.scope !== 'table' && task.code !== 'non_item_row'
              ? ' Resolve this problem for selected items, or edit exceptions individually.'
              : ''}
          </p>
        </div>
        {issues[0]?.scope === 'table' ? (
          <div className="p-5 space-y-4">
            <p className="text-sm text-gray-600">
              These columns apply to <strong>{task.itemIds.length} items</strong>
              {issues[0].worksheet ? ` in ${issues[0].worksheet}` : ''}. Confirm this once; individual rows do
              not need separate column checks.
            </p>
            <div className="grid sm:grid-cols-2 gap-2">
              {issues[0].columns
                ?.filter((column) => column.role !== 'attribute')
                .map((column) => (
                  <div key={column.key} className="rounded-lg border border-gray-200 px-3 py-2">
                    <span className="block text-xs text-gray-500">
                      Column {column.index} · {column.label}
                    </span>
                    <span className="block text-sm font-semibold mt-1">
                      {fieldLabels[column.role] ?? column.role.replace(/_/g, ' ')}
                    </span>
                  </div>
                ))}
            </div>
            <div className="border border-gray-200 rounded-lg overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Source row</th>
                    <th className="px-3 py-2 text-left">Copied product</th>
                    <th className="px-3 py-2 text-right">Requested quantity</th>
                  </tr>
                </thead>
                <tbody>
                  {issues[0].sampleRows?.map((row) => (
                    <tr key={row.itemId} className="border-t border-gray-100">
                      <td className="px-3 py-2 text-gray-500">{row.row ?? '—'}</td>
                      <td className="px-3 py-2">{row.name}</td>
                      <td className="px-3 py-2 text-right">{row.quantity ?? 'Missing'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-gray-500">
              Supplier quote columns are excluded. Confirming the layout preserves all item values and
              individual corrections.
            </p>
            <button
              type="button"
              className={primary}
              disabled={operations.busy}
              onClick={() =>
                void operations.preview({ action: 'accept', itemIds: [], issueIds: task.issueIds })
              }
            >
              Confirm columns for {task.itemIds.length} items
            </button>
          </div>
        ) : (
          <>
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
                    const reference = taskData.sourceReferences.find((r) => r.itemId === item.id);
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
                        <td className="p-3 min-w-44 font-medium">{item.name || 'Unnamed item'}</td>
                        <td className="p-3">
                          {task.category === 'type'
                            ? (item.domain ?? 'Not chosen')
                            : task.category === 'unit'
                              ? item.unit || '—'
                              : task.category === 'description'
                                ? item.name || 'Missing name'
                                : task.code === 'non_item_row'
                                  ? 'Repeated column labels'
                                  : task.category === 'source'
                                    ? 'Source reconciliation required'
                                    : task.category === 'other'
                                      ? issue?.fields.includes('notes')
                                        ? item.notes || 'Empty note'
                                        : `${item.quantity ?? 'Missing'} ${item.unit} · source check needed`
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
          </>
        )}
        {!members.length && (
          <p className="p-5 text-sm text-gray-600">
            {issues[0]?.evidence} Inspect the original document and add missed items from the full table.
          </p>
        )}
        <div className="p-5 border-t border-gray-200 space-y-3">
          {field && issues[0]?.scope !== 'table' && (
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
                      (i) =>
                        (rule === 'requested_total' ? (i.requestedTotal ?? 0) : (i.calculatedTotal ?? 0)) > 0,
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
          {task.canAccept && issues[0]?.scope !== 'table' && (
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <ReviewCheckbox
                label="I reviewed these items against the source"
                checked={!!draft.groupInspected}
                onChange={(checked) => update({ groupInspected: checked })}
              />
              I reviewed the selected items against the source
            </label>
          )}
          <div className="flex justify-between items-center gap-3 flex-wrap">
            {issues[0]?.scope === 'table' ? (
              <span className="text-xs text-gray-500">One decision for this source table</span>
            ) : task.code === 'non_item_row' ? (
              <button
                type="button"
                className={primary}
                disabled={operations.busy}
                onClick={() => void operations.preview({ action: 'remove', itemIds: task.itemIds })}
              >
                Remove {task.itemIds.length} repeated header {task.itemIds.length === 1 ? 'row' : 'rows'}
              </button>
            ) : task.canAccept ? (
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
            <button type="button" className={`${reviewButton} inline-flex items-center gap-2`} onClick={skip}>
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
      title={
        preview.tableDecision
          ? 'Confirm source columns'
          : operation.action === 'remove'
            ? `Remove ${operation.itemIds.length} items?`
            : 'Review changes'
      }
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
      {preview.tableDecision && (
        <div className="mb-4">
          <p className="text-sm text-gray-600 mb-3">
            Confirm these source columns for {preview.tableDecision.affectedItems} items
            {preview.tableDecision.worksheet ? ` in ${preview.tableDecision.worksheet}` : ''}. Existing item
            values stay unchanged.
          </p>
          <ul className="space-y-2 text-sm">
            {preview.tableDecision.columns
              .filter((column) => column.role !== 'attribute')
              .map((column) => (
                <li key={column.label}>
                  <span className="font-medium">{fieldLabels[column.role] ?? column.role}</span>:{' '}
                  {column.label}
                </li>
              ))}
          </ul>
        </div>
      )}
      {operation.action === 'accept' && !preview.tableDecision && (
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
