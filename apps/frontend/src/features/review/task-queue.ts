import type { ReviewTask } from '../../api/types';

export type TaskProgress = { current: string | null; after?: string | null; deferred: string[]; history: ReviewTask[] };

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
  const current = tasks.find(task => task.id === progress.current);
  if (current) return current;
  const history = taskHistory(progress.history, tasks);
  const position = history.findIndex(task => task.id === (progress.current ?? progress.after));
  if (position >= 0) {
    return history.slice(position + 1).map(step => tasks.find(task => task.id === step.id))
      .find(task => task && !progress.deferred.includes(task.id));
  }
  return tasks.find(task => !progress.deferred.includes(task.id));
}

export function deferTask(tasks: ReviewTask[], progress: TaskProgress, id: string): TaskProgress {
  const deferred = [...new Set([...progress.deferred, id])];
  const history = taskHistory(progress.history, tasks);
  const position = history.findIndex(task => task.id === id);
  const next = history.slice(position + 1).find(step => tasks.some(task => task.id === step.id) && !deferred.includes(step.id));
  return { ...progress, deferred, history, current: next?.id ?? null, after: id };
}

export function taskHistory(history: ReviewTask[], tasks: ReviewTask[]): ReviewTask[] {
  const current = new Map(tasks.map((task) => [task.id, task]));
  const known = new Set(history.map((task) => task.id));
  return [
    ...history.map((task) => current.get(task.id) ?? task),
    ...tasks.filter((task) => !known.has(task.id)),
  ];
}
