import type { ReviewTask } from '../../api/types';

export type TaskProgress = { current: string | null; deferred: string[]; history: ReviewTask[] };

export const requestDetailsTask: ReviewTask = {
  id: 'request-details',
  category: 'details',
  code: 'request_details',
  title: 'Review request details',
  itemIds: [],
  issueIds: [],
  suggestedValue: null,
  canAccept: false,
};

/** Request metadata is a separate guided step, never an item issue or matching blocker. */
export function reviewSteps(tasks: ReviewTask[], includeDetails: boolean) {
  return includeDetails ? [...tasks, requestDetailsTask] : tasks;
}

export function nextTask(tasks: ReviewTask[], progress: TaskProgress): ReviewTask | undefined {
  return (
    tasks.find((task) => task.id === progress.current) ??
    tasks.find((task) => !progress.deferred.includes(task.id))
  );
}

export function deferTask(tasks: ReviewTask[], progress: TaskProgress, id: string): TaskProgress {
  const deferred = [...new Set([...progress.deferred, id])];
  return { ...progress, deferred, current: tasks.find((task) => !deferred.includes(task.id))?.id ?? null };
}

export function taskHistory(history: ReviewTask[], tasks: ReviewTask[]): ReviewTask[] {
  const current = new Map(tasks.map((task) => [task.id, task]));
  const known = new Set(history.map((task) => task.id));
  return [
    ...history.map((task) => current.get(task.id) ?? task),
    ...tasks.filter((task) => !known.has(task.id)),
  ];
}
