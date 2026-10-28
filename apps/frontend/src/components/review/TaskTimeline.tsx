import { Check, Circle, Clock3 } from 'lucide-react';
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
  const open = new Set(tasks.map((task) => task.id));
  const done = history.filter((task) => !open.has(task.id)).length;
  return (
    <aside
      className="bg-white border border-gray-200 rounded-xl p-4 self-start lg:sticky lg:top-4"
      aria-label="Review timeline"
    >
      <h2 className="text-sm font-semibold">Your review plan</h2>
      <p className="text-xs text-gray-500 mt-1">
        {done} of {history.length} tasks resolved
      </p>
      <div className="flex gap-1 mt-3 mb-4" aria-label="Task progress">
        {history.map((task) => (
          <div
            key={task.id}
            title={task.title}
            className={`h-1.5 flex-1 rounded-full transition-colors duration-200 ${!open.has(task.id) ? 'bg-[#0E9E8F]' : task.id === current ? 'bg-[#1B4E8A]' : deferred.includes(task.id) ? 'bg-amber-300' : 'bg-gray-200'}`}
          />
        ))}
      </div>
      <ol className="space-y-1">
        {history.map((task, index) => {
          const resolved = !open.has(task.id),
            active = task.id === current,
            skipped = deferred.includes(task.id);
          const Icon = resolved ? Check : skipped ? Clock3 : Circle;
          return (
            <li key={task.id}>
              <button
                type="button"
                disabled={resolved}
                aria-current={active ? 'step' : undefined}
                onClick={() => onSelect(task.id)}
                className={`w-full flex gap-3 items-start text-left rounded-lg p-3 transition-colors ${active ? 'bg-blue-50 text-[#1B4E8A]' : resolved ? 'text-gray-400' : 'text-gray-700 hover:bg-gray-50'}`}
              >
                <span
                  className={`mt-0.5 flex h-6 w-6 items-center justify-center rounded-full flex-shrink-0 ${resolved ? 'bg-teal-50 text-[#0E9E8F]' : active ? 'bg-[#1B4E8A] text-white' : 'bg-gray-100'}`}
                >
                  {resolved || skipped ? <Icon size={13} /> : index + 1}
                </span>
                <span>
                  <span className="block text-sm font-medium leading-snug">
                    {task.title}
                    {task.suggestedValue ? ` · ${task.suggestedValue}` : ''}
                  </span>
                  <span className="block text-xs mt-1">
                    {resolved ? 'Resolved' : active ? 'Current' : skipped ? 'Review later' : 'Up next'}
                    {!resolved && task.itemIds.length
                      ? ` · ${task.itemIds.length} ${task.itemIds.length === 1 ? 'item' : 'items'}`
                      : ''}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-gray-400 mt-4">Skipped tasks stay open. Choose any task to return to it.</p>
    </aside>
  );
}
