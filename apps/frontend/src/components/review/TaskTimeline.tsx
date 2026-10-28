import { useEffect, useRef } from 'react';
import { Check, ChevronDown, Clock3, ListChecks } from 'lucide-react';
import type { ReviewTask } from '../../api/types';

export function TaskTimeline({
  history,
  tasks,
  current,
  deferred,
  onSelect,
}: {
  history: ReviewTask[];
  tasks: ReviewTask[];
  current: string | null;
  deferred: string[];
  onSelect: (id: string) => void;
}) {
  const picker = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (picker.current?.open && !picker.current.contains(event.target as Node)) picker.current.open = false;
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, []);
  const open = new Set(tasks.map((task) => task.id));
  const done = history.filter((task) => !open.has(task.id)).length;
  const skipped = tasks.filter((task) => deferred.includes(task.id));
  const ordered = [...tasks.filter((task) => !deferred.includes(task.id)), ...skipped];
  const position = history.findIndex((task) => task.id === current) + 1;
  return (
    <nav className="bg-white border border-gray-200 rounded-xl px-5 py-4" aria-label="Review timeline">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-40">
          <h2 className="text-sm font-semibold">
            {!tasks.length
              ? 'All tasks resolved'
              : current
                ? `Task ${position} of ${history.length}`
                : 'Review later'}
          </h2>
          <p className="text-xs text-gray-500 mt-0.5" aria-live="polite">
            {done} of {history.length} tasks resolved
            {skipped.length ? ` · ${skipped.length} set aside` : ''}
          </p>
        </div>
        <ol className="flex items-center gap-1.5 flex-1 min-w-52" aria-label="Task progress">
          {history.map((task) => {
            const resolved = !open.has(task.id);
            const active = task.id === current;
            const status = resolved
              ? 'Resolved'
              : active
                ? 'Current'
                : deferred.includes(task.id)
                  ? 'Review later'
                  : 'Up next';
            return (
              <li key={task.id} className="flex-1 min-w-0">
                <button
                  type="button"
                  disabled={resolved}
                  aria-label={`${task.title}: ${status}`}
                  aria-current={active ? 'step' : undefined}
                  title={`${task.title} · ${status}`}
                  onClick={() => onSelect(task.id)}
                  className="group w-full py-3 rounded focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"
                >
                  <span
                    className={`block h-2 rounded-full transition-colors duration-300 ${resolved ? 'bg-[#0E9E8F]' : active ? 'bg-[#1B4E8A]' : deferred.includes(task.id) ? 'bg-amber-400' : 'bg-gray-200 group-hover:bg-gray-300'}`}
                  />
                </button>
              </li>
            );
          })}
        </ol>
        <details
          ref={picker}
          className="relative"
          onKeyDown={(event) => {
            if (event.key === 'Escape' && picker.current?.open) {
              picker.current.open = false;
              picker.current.querySelector('summary')?.focus();
              event.stopPropagation();
            }
          }}
        >
          <summary className="list-none cursor-pointer flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-sm hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]">
            <ListChecks size={14} /> Remaining tasks ({tasks.length}) <ChevronDown size={13} />
          </summary>
          <div className="review-fade absolute right-0 top-full mt-2 w-80 max-w-[80vw] max-h-80 overflow-auto z-20 rounded-xl border border-gray-200 bg-white shadow-lg p-2">
            {!tasks.length && (
              <p className="p-3 text-sm text-gray-500">
                Every task is resolved. The full table is ready to inspect.
              </p>
            )}
            <ul>
              {ordered.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(task.id);
                      if (picker.current) picker.current.open = false;
                    }}
                    className="w-full flex gap-3 items-center text-left rounded-lg p-3 hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm font-medium">
                        {task.title}
                        {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
                      </span>
                      <span className="block text-xs text-gray-500 mt-1">
                        {task.code === 'request_details'
                          ? 'Partner, region and contact'
                          : task.itemIds.length
                            ? `${task.itemIds.length} ${task.itemIds.length === 1 ? 'item' : 'items'}`
                            : 'Document'}
                      </span>
                    </span>
                    <span
                      className={`text-xs inline-flex items-center gap-1 whitespace-nowrap ${task.id === current ? 'text-[#1B4E8A]' : deferred.includes(task.id) ? 'text-amber-700' : 'text-gray-400'}`}
                    >
                      {task.id === current ? (
                        'Current'
                      ) : deferred.includes(task.id) ? (
                        <>
                          <Clock3 size={12} /> Set aside
                        </>
                      ) : (
                        'Up next'
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {!!done && (
              <p className="border-t border-gray-100 mt-1 p-2 text-xs text-[#0E9E8F] flex items-center gap-1">
                <Check size={12} /> {done} resolved
              </p>
            )}
          </div>
        </details>
      </div>
    </nav>
  );
}
