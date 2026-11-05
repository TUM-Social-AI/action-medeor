import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, CheckCircle2, FileText, ListChecks, SkipForward, X } from 'lucide-react';
import type { ExtractedItem, ItemUpdate, ReviewIssue, ReviewResponse } from '../../api/types';
import {
  nextTask,
  deferTask,
  taskHistory,
  reviewSteps,
  requestDetailsTask,
  type TaskProgress,
} from '../../features/review/task-queue';
import { TaskTimeline } from './TaskTimeline';
import type { ReviewOperations } from '../../features/review/use-review-operations';
import { guidedColumnLabel, guidedExpectation, guidedValues, keepLabel } from '../../features/review/guided-values';

export const reviewInput =
  'border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white outline-none focus:ring-2 focus:ring-[#1B4E8A]/20 focus:border-[#1B4E8A]';
export const reviewButton =
  'px-3 py-2 rounded-lg border border-gray-300 text-sm hover:bg-gray-50 disabled:opacity-50';
const primary = 'px-4 py-2 rounded-lg text-sm bg-[#1B4E8A] text-white hover:bg-[#163d6d] disabled:opacity-50';
const keepButton = 'px-4 py-2 rounded-lg text-sm border border-teal-300 bg-teal-50 text-teal-800 hover:bg-teal-100 disabled:opacity-50';
const removeButton = 'px-4 py-2 rounded-lg text-sm border border-red-200 bg-red-50 text-red-800 hover:bg-red-100 disabled:opacity-50';
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
  quantity_packs: 'Number of packs', units_per_pack: 'Units per pack',
  translation: 'Translation', attribute: 'Additional field', ordinal: 'Row number',
};

function previewValue(field: string, value: unknown) {
  if (field === 'removed_at') return value ? 'Removed' : 'Active';
  if (field === 'verification_source')
    return value === 'human' ? 'Human verified' : value === 'ai' ? 'AI checked' : 'Ready';
  return value === null || value === undefined || value === '' ? 'Empty' : String(value);
}

function hasPackCalculation(issue?: ReviewIssue) {
  return (issue?.packs ?? 0) > 0 && (issue?.unitsPerPack ?? 0) > 0 && (issue?.calculatedTotal ?? 0) > 0;
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
  const [expanded, setExpanded] = useState(false);
  const problemList = useRef<HTMLDivElement>(null);
  const shownTasks = expanded ? tasks : tasks.slice(0, 3);
  return (
    <section
      className="review-overview flex flex-col bg-white rounded-xl border border-gray-200 p-4 mb-4"
      aria-label="Review overview"
    >
      <div className="flex items-center gap-2 text-[#1B4E8A] mb-2 shrink-0">
        <ListChecks size={20} />
        <h2 className="text-lg text-gray-900">Review related problems together</h2>
      </div>
      <p className="text-sm text-gray-500 mb-3 shrink-0">
        We’ve grouped related problems so you can review several items together.
      </p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3 shrink-0">
        {[
          [counts?.active ?? data.items.length, 'Active items'],
          [counts?.ready ?? 0, 'Ready'],
          [counts?.affected ?? 0, 'Need attention'],
          [tasks.length, 'Review tasks'],
        ].map(([value, label]) => (
          <div key={label} className="rounded-lg border border-gray-200 p-3">
            <div className="text-2xl font-semibold text-gray-900">{value}</div>
            <div className="text-xs text-gray-500 mt-1">{label}</div>
          </div>
        ))}
      </div>
      {!!tasks.length && (
        <div
          ref={problemList}
          id="overview-review-problems"
          role="region"
          aria-label="Review problems"
          tabIndex={0}
          className="min-h-0 max-h-64 overflow-y-auto overscroll-contain divide-y divide-gray-100 rounded focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"
          style={{ scrollbarGutter: 'stable' }}
        >
          {shownTasks.map((task) => (
            <div key={task.id} className="flex justify-between gap-4 py-1.5 text-sm">
              <span className="text-gray-700">
                {task.title}
                {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
              </span>
              <span className="text-gray-500 shrink-0">
                {task.code === 'request_details'
                  ? 'Optional fields'
                  : task.itemIds.length
                    ? `${task.itemIds.length} ${task.itemIds.length === 1 ? 'item' : 'items'}`
                    : 'Document'}
              </span>
            </div>
          ))}
        </div>
      )}
      {tasks.length > 3 && (
        <div className="flex justify-between items-center gap-3 mt-2 shrink-0 text-xs">
          <span className="text-gray-400">
            {expanded ? `${tasks.length} problems` : `Showing 3 of ${tasks.length} problems`}
          </span>
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls="overview-review-problems"
            className="px-2 py-1 rounded text-[#1B4E8A] hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"
            onClick={() => {
              setExpanded(!expanded);
              if (problemList.current) problemList.current.scrollTop = 0;
            }}
          >
            {expanded ? 'Show fewer' : `View all ${tasks.length} problems`}
          </button>
        </div>
      )}
      {!tasks.length && (
        <p className="text-sm text-green-700 shrink-0">
          No open review tasks. Check the complete list before matching.
        </p>
      )}
      <div className="flex gap-3 mt-3 pt-3 border-t border-gray-100 shrink-0">
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

export function SourceColumnReview({ issue, total, operations, onSkip }: { issue: ReviewIssue; total: number; operations: ReviewOperations; onSkip?: () => void }) {
  const columns = issue.columns ?? [];
  const [roles, setRoles] = useState<Record<string, string>>(() => Object.fromEntries(columns.map(col => [col.key, col.role])));
  const changed = columns.some(col => roles[col.key] !== col.role);
  return <div className="p-5 space-y-4">
    <p className="text-sm text-gray-600"><strong>{issue.worksheet || 'This source table'}</strong> · {issue.itemIds?.length ?? 0} affected items out of {total} in this request. Other worksheets or tables have their own mappings.</p>
    <div className="grid sm:grid-cols-2 gap-3 max-h-80 overflow-y-auto overscroll-contain">
      {columns.map(col => <label key={col.key} className="rounded-lg border border-gray-200 p-3">
        <span className="block text-xs text-gray-500 mb-2">Column {col.index} · {col.label}</span>
        <select className={`${reviewInput} w-full`} aria-label={`Map ${col.label}`} value={roles[col.key]}
          onChange={e => setRoles(previous => ({ ...previous, [col.key]: e.target.value }))} disabled={operations.busy}>
          {['name', 'quantity', 'quantity_packs', 'units_per_pack', 'unit', 'domain', 'notes', 'item_number', 'shelf_life', 'priority', 'translation', 'attribute', 'ordinal'].map(role => <option key={role} value={role}>{fieldLabels[role] ?? role}</option>)}
        </select>
        {roles[col.key] !== col.role && <span className="block text-xs text-gray-500 mt-1">Existing: {fieldLabels[col.role] ?? col.role}</span>}
      </label>)}
    </div>
    <details>
      <summary className="text-sm cursor-pointer text-[#1B4E8A]">View source rows ({issue.sampleRows?.length ?? 0} examples)</summary>
      <div className="overflow-auto mt-2"><table className="w-full text-xs"><thead><tr><th className="p-2 text-left">Row</th>{columns.map(col => <th key={col.key} className="p-2 text-left">{col.label}</th>)}</tr></thead>
        <tbody>{issue.sampleRows?.map(row => <tr key={row.itemId} className="border-t border-gray-100"><td className="p-2">{row.row ?? '—'}</td>{columns.map(col => <td key={col.key} className="p-2">{row.cells[col.key] || '—'}</td>)}</tr>)}</tbody></table></div>
    </details>
    <p className="text-xs text-gray-500">Changing a mapping shows the copied field changes before you save. Manual field corrections are preserved.</p>
    <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap gap-2">
      <button type="button" className={keepButton} disabled={operations.busy}
        onClick={() => void operations.accept({ itemIds: [], issueIds: [issue.id] })}>Keep existing mapping</button>
      <button type="button" className={primary} disabled={operations.busy || !changed}
        onClick={() => void operations.preview({ action: 'column_mapping', itemIds: issue.itemIds ?? [], issueIds: [issue.id], columnRoles: roles })}>Change column mapping</button>
    </div>{onSkip && <button type="button" className={reviewButton} disabled={operations.busy} onClick={onSkip}>Skip</button>}</div>
  </div>;
}

export function MissingItemsReview({ issues, items, operations, onAdd, onEdit, usedItemIds = [] }: {
  issues: ReviewIssue[]; items: ExtractedItem[]; operations: ReviewOperations;
  onAdd?: (issueId: string, context: string) => void;
  onEdit: (item: ExtractedItem, fields?: string[]) => void;
  usedItemIds?: number[];
}) {
  const [existing, setExisting] = useState<Record<string, string>>({});
  const used = new Set([...usedItemIds, ...issues.filter(issue => issue.state === 'accepted').map(issue => issue.addedItemId)]);
  const available = items.filter(item => item.manual && !used.has(item.id));
  return <div className="p-5 space-y-3">
    <p className="text-sm text-gray-600">Fill each missing item separately. Saving replaces its warning with the completed item.</p>
    {issues.map((issue, index) => {
      const filled = issue.state === 'accepted' ? items.find(item => item.id === issue.addedItemId) : undefined;
      if (filled) return <div key={issue.id} className="rounded-lg border border-teal-200 bg-teal-50 p-4">
        <div className="text-xs font-semibold text-teal-700 mb-1">Item {index + 1} · Added</div>
        <button type="button" className="font-semibold text-left text-[#1B4E8A] hover:underline" onClick={() => onEdit(filled)}>{filled.name}</button>
        <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <div><dt className="inline text-gray-500">Quantity: </dt><dd className="inline">{filled.quantity?.toLocaleString()}</dd></div>
          <div><dt className="inline text-gray-500">Unit: </dt><dd className="inline">{filled.unit || '—'}</dd></div>
          <div><dt className="inline text-gray-500">Type: </dt><dd className="inline">{filled.domain}</dd></div>
        </dl>
        {filled.notes && <p className="text-sm text-gray-600 mt-2">{filled.notes}</p>}
      </div>;
      if (issue.state === 'accepted') return <p key={issue.id} className="text-sm text-gray-500">Item {index + 1} · Warning dismissed</p>;
      return <div key={issue.id} className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
        <div><div className="text-xs font-semibold text-amber-800 mb-1">Missing item {index + 1}</div><p className="text-sm font-medium text-amber-900">{issue.message}</p></div>
        {issue.evidence && issue.evidence !== issue.message && <details className="text-xs text-gray-600"><summary className="cursor-pointer">Source context</summary><p className="mt-2 whitespace-pre-wrap">{issue.evidence}</p></details>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={keepButton} disabled={operations.busy}
            onClick={() => void operations.accept({ itemIds: issue.itemId == null ? [] : [issue.itemId], issueIds: [issue.id] })}>Not a missing item</button>
          <button type="button" className={primary} disabled={operations.busy || !onAdd}
            onClick={() => onAdd?.(issue.id, issue.message)}>Add this item</button>
        </div>
        {!!available.length && <details><summary className="text-xs cursor-pointer text-[#1B4E8A]">Use an item already added</summary>
          <div className="mt-2 flex gap-2 flex-wrap">
            <select className={reviewInput} aria-label={`Existing item for missing item ${index + 1}`} value={existing[issue.id] ?? ''}
              onChange={event => setExisting(current => ({ ...current, [issue.id]: event.target.value }))} disabled={operations.busy}>
              <option value="">Choose an added item</option>{available.map(item => <option key={item.id} value={item.id}>{item.name} · {item.quantity} {item.unit}</option>)}
            </select>
            <button type="button" className={primary} disabled={operations.busy || !existing[issue.id]}
              onClick={() => void operations.resolveMissing({ issueId: issue.id, itemId: Number(existing[issue.id]) })}>Use this item</button>
          </div>
        </details>}
      </div>;
    })}
    {operations.error && <p role="alert" className="text-sm text-red-700">{operations.error}</p>}
  </div>;
}

export function GuidedReview({
  data,
  hidden,
  operations,
  onEdit,
  onAll,
  onAdd,
  requestDetails,
}: {
  data: ReviewResponse;
  hidden: boolean;
  operations: ReviewOperations;
  onEdit: (item: ExtractedItem, fields?: string[]) => void;
  onAll: () => void;
  onAdd?: (issueId: string, sourceContext: string) => void;
  requestDetails?: { content: ReactNode; confirmed: boolean; open: boolean; visit: number };
}) {
  const [progress, setProgress] = useState(() => {
    const saved = readProgress(data.requestId);
    return { ...saved, history: taskHistory(saved.history, data.tasks ?? []) };
  });
  const [drafts, setDrafts] = useState<
    Record<string, { value: string; selected: number[] }>
  >({});
  const tasks = reviewSteps(
    data.tasks ?? [],
    !!requestDetails && (!requestDetails.confirmed || requestDetails.open),
  );
  const target = nextTask(tasks, progress);
  const history = taskHistory(progress.history, requestDetails ? reviewSteps(data.tasks ?? [], true) : tasks);
  const [display, setDisplay] = useState<{ task: typeof target; data: ReviewResponse }>({
    task: target,
    data,
  });
  const displayId = useRef(target?.id);
  const resolvedTransition = useRef(false);
  const lastDetailsVisit = useRef(0);
  const [phase, setPhase] = useState<'hold' | 'in' | 'out' | 'idle'>('idle');
  useEffect(() => {
    const visit = requestDetails?.visit ?? 0;
    const requestedDetails = visit !== lastDetailsVisit.current && visit > 0;
    lastDetailsVisit.current = visit;
    if (requestedDetails) {
      setProgress((p) => ({ ...p, history, current: requestDetailsTask.id }));
    } else if (!hidden && target) {
      // A partial save can reorder the server's task list. Keep the displayed task pinned
      // until it is resolved, skipped, or explicitly changed by the user.
      setProgress((p) =>
        tasks.some((task) => task.id === p.current) ? p : { ...p, history, current: target.id },
      );
    }
  }, [hidden, target?.id, requestDetails?.visit]);
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
      tasks={tasks.filter((task) => task.code !== 'request_details' || !requestDetails?.confirmed)}
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
              <h2>{tasks.some(task => !progress.deferred.includes(task.id)) ? 'End of review sequence' : 'Remaining tasks are set aside'}</h2>
              <p className="text-sm text-gray-500 mt-2 mb-5">
                {tasks.length} earlier or skipped tasks are still open. Choose one in the timeline or review the remaining tasks.
              </p>
              <button
                type="button"
                className={primary}
                onClick={() =>
                  setProgress((p) => ({ ...p, history, current: tasks[0]?.id ?? null, after: null, deferred: [] }))
                }
              >
                Review remaining tasks
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
  };
  const update = (patch: Partial<typeof draft>) =>
    setDrafts((previous) => ({ ...previous, [task.id]: { ...draft, ...patch } }));
  const selected = draft.selected.filter((id) => task.itemIds.includes(id));
  const members = taskData.items.filter((item) => task.itemIds.includes(item.id));
  const issues = (taskData.issues ?? []).filter((issue) => task.issueIds.includes(issue.id));
  const selectedIssues = issues.filter((i) => i.itemId === null || selected.includes(i.itemId));
  const ruleIssues = selectedIssues.length ? selectedIssues : issues;
  const packTargets = [...new Set(ruleIssues.map(issue => issue.calculatedTotal))];
  const field =
    task.category === 'type'
      ? 'domain'
      : task.category === 'quantity' || task.category === 'totals'
        ? 'quantity'
        : task.category === 'unit'
          ? 'unit'
          : null;
  const individual = task.category === 'description';
  const coverage = task.code === 'coverage_uncertain';
  const coverageIssues = (taskData.issues ?? []).filter(issue => issue.code === 'coverage_uncertain' &&
    (task.issueIds.includes(issue.id) || (!!issues[0]?.sourceScope && issue.sourceScope === issues[0].sourceScope &&
      JSON.stringify(issue.fields) === JSON.stringify(issues[0].fields))));
  const repeated = task.code === 'non_item_row';
  const fullRowCheck = task.code === 'low_confidence' || task.code === 'confirmation_required';
  const sourceValue = (item: ExtractedItem) => {
    const issue = issues.find(issue => issue.itemId === item.id);
    if (field === 'domain') {
      const value = issue?.sourceType ?? issue?.sourceValues?.domain?.toLowerCase();
      return value === 'medicine' || value === 'equipment' ? value : null;
    }
    if (field === 'unit') return issue?.sourceValues?.unit || null;
    if (field === 'quantity') return (issue?.requestedTotal ?? 0) > 0 ? issue!.requestedTotal! : null;
    return null;
  };
  const useSource = !!field && selected.length > 0 && selected.every(id => {
    const item = members.find(item => item.id === id)!;
    return sourceValue(item) !== null;
  }) && selected.some(id => {
    const item = members.find(item => item.id === id)!;
    return sourceValue(item) !== item[field as keyof ExtractedItem];
  });
  const changeToSource = () => {
    if (!field) return;
    if (field === 'quantity') { void operations.preview({ action: 'quantity_rule', itemIds: selected, rule: 'requested_total' }); return; }
    void operations.preview({ action: 'edit', itemIds: selected, itemChanges: Object.fromEntries(selected.map(id => {
      const item = members.find(item => item.id === id)!;
      return [id, { [field]: sourceValue(item) }];
    })) });
  };
  const makeChange = (value = draft.value) => {
    if (!field) return;
    if (field === 'quantity' && task.category === 'totals') {
      void operations.preview({ action: 'quantity_rule', itemIds: selected, rule: 'explicit', changes: { quantity: Number(value) } });
      return;
    }
    void operations.preview({
      action: 'edit',
      itemIds: selected,
      changes: { [field]: field === 'quantity' ? Number(value) : value },
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
        {task.code === 'request_details' ? (
          <>
            {requestDetails?.content}
            {!requestDetails?.confirmed && (
              <div className="px-5 py-3 border-t border-gray-100 flex justify-end">
                <button type="button" className={reviewButton} onClick={skip}>
                  Review later
                </button>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="p-5 border-b border-gray-200">
              <h2 className="text-lg">
                {task.title}
                {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
              </h2>
              <p className="text-sm text-gray-500 mt-1">
                {coverage ? 'Compare the extracted products with the source.' : issues[0]?.message}
                {!coverage && issues[0]?.message && !/[.!?]$/.test(issues[0].message.trim()) ? '.' : ''}
              </p>
            </div>
            {issues[0]?.scope === 'table' ? (
              <SourceColumnReview key={issues[0].id} issue={issues[0]} total={taskData.items.length} operations={operations} onSkip={skip} />
            ) : coverage ? (
              <MissingItemsReview issues={coverageIssues} items={taskData.items} operations={operations} onAdd={onAdd} onEdit={onEdit}
                usedItemIds={(taskData.issues ?? []).filter(issue => issue.state === 'accepted' && issue.addedItemId != null).map(issue => issue.addedItemId!)} />
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-gray-500">
                      <tr>
                        {!individual && <th className="p-3 w-10">
                          <ReviewCheckbox
                            label="Select all task items"
                            checked={selected.length === members.length && !!members.length}
                            mixed={!!selected.length && selected.length < members.length}
                            disabled={operations.busy}
                            onChange={(checked) => update({ selected: checked ? task.itemIds : [] })}
                          />
                        </th>}
                        <th className="p-3 text-left">Item</th>
                        <th className="p-3 text-left">{fullRowCheck ? 'Review status' : guidedColumnLabel(task)}</th>
                        <th className="p-3 text-left">{fullRowCheck ? 'Values to verify' : 'What needs checking'}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {members.map((item) => {
                        const issue = issues.find((i) => i.itemId === item.id);
                        const reference = taskData.sourceReferences.find((r) => r.itemId === item.id);
                        const expectation = guidedExpectation(task, item, issue);
                        return (
                          <tr key={item.id} className="border-t border-gray-100">
                            {!individual && <td className="p-3">
                              <ReviewCheckbox
                                label={`Select ${item.name}`}
                                checked={selected.includes(item.id)}
                                disabled={operations.busy}
                                onChange={(checked) =>
                                  update({
                                    selected: checked
                                      ? [...selected, item.id]
                                      : selected.filter((id) => id !== item.id),
                                  })
                                }
                              />
                            </td>}
                            <td className="p-3 min-w-44 max-w-sm font-medium align-top">
                              <button type="button" className="text-left text-[#1B4E8A] hover:underline" disabled={operations.busy}
                                onClick={() => onEdit(item, issue?.fields)}>{item.name || 'Unnamed item'}</button>
                              <button type="button" disabled={operations.busy} onClick={() => onEdit(item, issue?.fields)}
                                className={`${reviewButton} block mt-2 text-xs font-normal py-1 px-2`}>
                                Edit item
                              </button>
                            </td>
                            <td className="p-3 min-w-36 align-top">
                              {fullRowCheck ? <p className="text-sm text-amber-800">Source check needed</p> : <dl className="space-y-1">
                                {guidedValues(task, item, issue).map(value => (
                                  <div key={value.field}>
                                    <dt className="inline text-xs text-gray-500">{value.label}: </dt>
                                    <dd className={`inline font-medium ${task.category === 'unit' ? 'text-amber-800 bg-amber-50 px-1.5 py-0.5 rounded' : 'text-gray-900'}`}>{value.value}</dd>
                                  </div>
                                ))}
                              </dl>}
                              {task.category === 'unit' && <p className="mt-2 text-xs text-gray-500">Quantity: {item.quantity?.toLocaleString() ?? 'Missing'}</p>}
                            </td>
                            <td className="p-3 min-w-56 max-w-md align-top">
                              {fullRowCheck ? <dl className="space-y-1 text-sm">
                                {['name', 'quantity', 'unit', 'domain', ...(item.notes ? ['notes'] : [])].map(key => <div key={key}>
                                  <dt className="inline text-xs text-gray-500">{fieldLabels[key]}: </dt>
                                  <dd className="inline font-medium">{issue?.sourceValues?.[key] || String(item[key as keyof ExtractedItem] ?? 'Missing')}</dd>
                                </div>)}
                              </dl> : <div className={task.code === 'pack_total_conflict' ? 'border border-red-200 bg-red-50 rounded-lg p-3' : ''}>
                                <div className="text-xs text-gray-500">{expectation.label}</div>
                                <p className={`text-sm font-semibold mt-0.5 ${task.code === 'pack_total_conflict' ? 'text-red-700' : 'text-amber-900'}`}>{expectation.value}</p>
                                {expectation.detail && <p className="text-xs text-gray-500 mt-1">{expectation.detail}</p>}
                              </div>}
                              {individual && <div className="flex flex-wrap gap-2 mt-3">
                                {issue?.canAccept && <button type="button" className={keepButton} disabled={operations.busy}
                                  onClick={() => void operations.accept({ itemIds: [item.id], issueIds: [issue.id] })}>Keep description</button>}
                                {issue?.sourceValues?.name && issue.sourceValues.name !== item.name && <button type="button" className={primary} disabled={operations.busy}
                                  onClick={() => void operations.preview({ action: 'edit', itemIds: [item.id], changes: { name: issue.sourceValues!.name } })}>Use source description</button>}
                              </div>}
                              <details className="mt-2">
                                <summary className="cursor-pointer text-xs text-[#1B4E8A]">
                                  View source{reference?.row && reference.row > 0 ? ` · row ${reference.row}` : reference?.page && reference.page > 0 ? ` · page ${reference.page}` : ''}
                                </summary>
                                {reference?.illustrative && <p className="mt-2 text-xs text-violet-700">Illustrative example · source workbook values are simulated.</p>}
                                {reference?.cells?.length ? <dl className="mt-2 border border-slate-200 bg-slate-50 rounded-lg p-3 space-y-2 text-xs">
                                  {reference.cells.filter(cell => !cell.exampleNote).map(cell => <div key={cell.index} className="grid grid-cols-[minmax(5rem,1fr)_2fr] gap-2">
                                    <dt className="text-gray-500">{cell.label}</dt><dd className="text-gray-800 whitespace-pre-wrap">{cell.value}</dd>
                                  </div>)}
                                </dl> : <p className="mt-2 p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-gray-800 whitespace-pre-wrap">{reference?.excerpt || issue?.evidence || 'No source reference available. Check the original document.'}</p>}
                                {reference?.cells?.some(cell => cell.exampleNote) && <details className="mt-2 text-xs text-violet-800"><summary className="cursor-pointer">Example annotations (fixture instructions)</summary>
                                  {reference.cells.filter(cell => cell.exampleNote).map(cell => <p key={cell.index} className="mt-1">{cell.label}: {cell.value}</p>)}
                                </details>}
                              </details>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {!members.length && !coverage && issues[0]?.scope !== 'table' && (
              <p className="p-5 text-sm text-gray-600">
                {issues[0]?.evidence} Inspect the original document and add missed items from the full table.
              </p>
            )}
            {issues[0]?.scope !== 'table' && <div className="p-5 border-t border-gray-200 space-y-3">
              {field && !individual && !coverage && !repeated && issues[0]?.scope !== 'table' &&
                !(task.code === 'type_conflict' || task.code === 'pack_total_conflict' || field === 'unit' && useSource) && (
                <div className="flex flex-wrap items-center gap-3">
                  <label className="text-sm text-gray-600" htmlFor={`task-value-${task.id}`}>New {field === 'domain' ? 'product type' : field}</label>
                  {field === 'domain' ? <select id={`task-value-${task.id}`} className={reviewInput} value={draft.value}
                    onChange={e => update({ value: e.target.value })} disabled={operations.busy}>
                    <option value="">Choose type</option><option value="medicine">Medicine</option><option value="equipment">Equipment</option>
                  </select> : <input id={`task-value-${task.id}`} className={reviewInput} type={field === 'quantity' ? 'number' : 'text'}
                    min={1} step={1} value={draft.value} placeholder={field === 'unit' ? 'Stück (default)' : field === 'quantity' && useSource ? selected.length === 1 ? String(ruleIssues[0]?.requestedTotal ?? '') : 'Source value for each row' : undefined}
                    onChange={e => update({ value: e.target.value })} disabled={operations.busy} />}
                  {field === 'unit' && <span className="text-xs text-gray-500">Quantity stays unchanged. Leave empty to choose Stück.</span>}
                </div>
              )}
              {!individual && !coverage && issues[0]?.scope !== 'table' && <p className="text-xs text-gray-500">
                {selected.length} {selected.length === 1 ? 'item' : 'items'} selected · Keep confirms this check. Change shows the changes before saving.
              </p>}
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                  {coverage || issues[0]?.scope === 'table' || individual ? null : <>
                    {task.canAccept && <button type="button" className={keepButton} disabled={operations.busy || !selectedIssues.length}
                      aria-busy={operations.busy} onClick={() => void operations.accept({ itemIds: selected, issueIds: selectedIssues.map(issue => issue.id) })}>{keepLabel(task)}</button>}
                    {repeated ? <button type="button" className={removeButton} disabled={operations.busy || !selected.length}
                      onClick={() => void operations.preview({ action: 'remove', itemIds: selected })}>Remove repeated header row{selected.length > 1 ? 's' : ''}</button>
                    : task.code === 'pack_total_conflict' ? <button type="button" className={primary}
                      disabled={operations.busy || !selected.length || !ruleIssues.every(issue => hasPackCalculation(issue))}
                      onClick={() => void operations.preview({ action: 'quantity_rule', itemIds: selected, rule: 'pack_calculation' })}>
                      {packTargets.length === 1 && packTargets[0] != null ? `Update to ${packTargets[0].toLocaleString()}` : 'Update to pack totals'}
                    </button>
                    : task.code === 'type_conflict' || field === 'unit' && useSource ? <button type="button" className={primary}
                      disabled={operations.busy || !useSource} onClick={changeToSource}>Change to source {field === 'domain' ? 'type' : 'unit'}</button>
                    : field ? <button type="button" className={primary}
                      disabled={operations.busy || !selected.length || (!draft.value && !useSource && field !== 'unit') || (field === 'quantity' && !!draft.value && (!Number.isInteger(Number(draft.value)) || Number(draft.value) <= 0))}
                      onClick={() => {
                        const matchesSource = field === 'quantity' && useSource && selected.every(id => Number(draft.value) === sourceValue(members.find(item => item.id === id)!));
                        if ((!draft.value && useSource) || matchesSource) changeToSource(); else makeChange(field === 'unit' && !draft.value ? 'Stück' : draft.value);
                      }}>{field === 'unit' && !draft.value && !useSource ? 'Use Stück (default)' : `Change ${field === 'domain' ? 'product type' : field}`}</button>
                    : <button type="button" className={primary} disabled={operations.busy || selected.length !== 1}
                      onClick={() => onEdit(members.find(item => item.id === selected[0])!, issues.find(issue => issue.itemId === selected[0])?.fields)}>Edit selected item</button>}
                  </>}
                </div>
                <button type="button" className={`${reviewButton} inline-flex items-center gap-2`} onClick={skip} disabled={operations.busy}>
                  <SkipForward size={14} /> Skip
                </button>
              </div>
            </div>}
          </>
        )}
      </div>
    </section>
  );
}

export function OperationPreview({ operations }: { operations: ReviewOperations }) {
  const pending = operations.pending;
  if (!pending) return null;
  const { preview, operation } = pending;
  const itemLabel = operation.itemIds.length === 1 ? 'item' : 'items';
  const title = {
    edit: 'Review item changes',
    quantity_rule: 'Review quantity changes',
    verify: `Verify ${itemLabel}?`,
    accept: preview.tableDecision ? 'Confirm column mapping' : 'Confirm source check',
    remove: `Remove ${operation.itemIds.length} ${itemLabel}?`,
    restore: `Restore ${itemLabel}?`,
    column_mapping: 'Change source columns',
  }[operation.action];
  const confirmLabel = {
    edit: 'Save changes',
    quantity_rule: 'Update quantities',
    verify: `Verify ${itemLabel}`,
    accept: preview.tableDecision ? 'Confirm column mapping' : 'Keep values',
    remove: `Remove ${itemLabel}`,
    restore: `Restore ${itemLabel}`,
    column_mapping: 'Apply column mapping',
  }[operation.action];
  return (
    <ReviewDialog
      title={title}
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
            {operation.action === 'column_mapping' ? 'Apply these source columns to ' : 'Confirm these source columns for '}{preview.tableDecision.affectedItems} items
            {preview.tableDecision.worksheet ? ` in ${preview.tableDecision.worksheet}` : ''}. Existing item
            {operation.action === 'column_mapping' ? 'field changes are listed below. Manual field corrections are preserved.' : 'values stay unchanged.'}
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
          {operation.rule === 'explicit' ? 'Use the entered quantity for the selected items.' : operation.rule === 'requested_total'
            ? 'Use each row’s requested total.'
            : 'Use each row’s pack calculation.'}{' '}
          This records your interpretation of the conflicting source quantities.
        </p>
      )}
      <div className="max-h-80 overflow-auto divide-y divide-gray-100">
        {preview.changes.map((change) => (
          <div key={change.itemId} className="py-3">
            <div className="text-sm font-medium">{change.name}</div>
            {Object.entries(change.keptValues ?? {}).map(([field, value]) => (
              <p key={field} className="text-sm text-gray-600 mt-1">
                Keep {fieldLabels[field] ?? field}: <span className="font-medium text-gray-900">{previewValue(field, value)}</span>
              </p>
            ))}
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
          {operations.busy ? 'Saving…' : confirmLabel}
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
    <nav aria-label="Review views" className="inline-flex gap-1 rounded-lg bg-gray-100 p-0.5">
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
          className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs transition-colors ${view === key ? 'bg-white text-[#1B4E8A] font-semibold shadow-sm' : 'text-gray-500 hover:text-gray-900'}`}
          onClick={() => setView(key)}
        >
          <Icon size={14} />
          {label}
        </button>
      ))}
    </nav>
  );
}
