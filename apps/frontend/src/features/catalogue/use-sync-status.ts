import { useEffect, useRef, useState } from 'react';
import {
  getCatalogueSyncStatus, type CatalogueFetchAccepted, type CatalogueSyncRun,
} from '../../api/catalogue';

const POLL_MS = 5000;
const START_TIMEOUT_MS = 5 * 60 * 1000;
const TERMINAL_NOTICE_MS = 8000;

function describe(run: CatalogueSyncRun): string {
  if (run.status === 'running') return 'Fetching new data from SharePoint…';
  if (run.status === 'failed') return run.message ?? 'SharePoint fetch failed. Check the job logs.';
  if (run.status === 'stale') return run.message ?? 'The fetch has stopped reporting progress. Check the Azure job execution logs.';
  if (run.status === 'skipped') return 'Fetch skipped because another discovery was already running.';
  if (run.summary.processing_enabled === false) return 'SharePoint discovery completed. Offer processing is disabled for this job.';
  if (run.summary.deferred) {
    const count = run.summary.deferred;
    const processed = run.summary.processed ?? 0;
    const message = run.message ?? `Processing budget reached. Progress saved for ${count} unfinished document${count === 1 ? '' : 's'}. Processing will continue on a later sync.`;
    return `Fetch finished. ${processed} document${processed === 1 ? '' : 's'} processed. ${message}`;
  }
  return `Fetch completed. ${run.summary.processed ?? 0} documents processed. The catalogue has been refreshed.`;
}

export function useCatalogueSyncStatus(onFinished: () => void) {
  const [runs, setRuns] = useState<CatalogueSyncRun[]>([]);
  const [watch, setWatch] = useState<(CatalogueFetchAccepted & { waitingSince: number }) | null>(null);
  const [statusKnown, setStatusKnown] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [startTimedOut, setStartTimedOut] = useState(false);
  const [dismissedNoticeKey, setDismissedNoticeKey] = useState<string | null>(null);
  const finished = useRef<Set<string> | null>(null);
  const refresh = useRef(onFinished);
  refresh.current = onFinished;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const data = await getCatalogueSyncStatus(controller.signal);
        if (controller.signal.aborted) return;
        setRuns(data.runs);
        setStatusKnown(true);
        setStatusError(null);
        const terminal = data.runs.filter(run => run.status === 'completed' || run.status === 'failed');
        const unseen = terminal.filter(run => !finished.current?.has(run.id));
        const requested = watch && data.runs
          .filter(run => watch.execution_name
            ? run.execution_name === watch.execution_name
            : Date.parse(run.started_at) >= Date.parse(watch.requested_at))
          .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))[0];
        if ((finished.current !== null && unseen.length > 0)
          || (requested && unseen.includes(requested) && terminal.includes(requested))) refresh.current();
        finished.current ??= new Set();
        terminal.forEach(run => finished.current!.add(run.id));
        if (watch && requested) {
          setStartTimedOut(false);
          if (requested.status !== 'running') setWatch(null);
        }
        if (watch && !requested && Date.now() - watch.waitingSince >= START_TIMEOUT_MS) {
          setStartTimedOut(true);
        }
      } catch {
        if (!controller.signal.aborted) {
          setStatusKnown(false);
          setStatusError('Could not read fetch status. Retrying automatically…');
        }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => void poll(), POLL_MS);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [watch]);

  const requested = watch
    ? [...runs].filter(run => watch.execution_name
      ? run.execution_name === watch.execution_name
      : Date.parse(run.started_at) >= Date.parse(watch.requested_at))
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))[0]
    : undefined;
  const active = runs.find(run => run.status === 'running');
  const displayed = requested ?? active ?? runs[0];
  const busy = Boolean((watch && !startTimedOut) || active);
  const terminalRun = !busy && displayed?.status !== 'running' ? displayed : undefined;
  const noticeAt = terminalRun?.finished_at ?? terminalRun?.updated_at ?? null;
  const noticeKey = terminalRun ? `${terminalRun.id}:${terminalRun.status}:${noticeAt}` : null;
  const showTerminalNotice = noticeKey !== dismissedNoticeKey && noticeAt !== null
    && Date.now() < Date.parse(noticeAt) + TERMINAL_NOTICE_MS;
  const lastUpdatedAt = runs.filter(run => run.status === 'completed')
    .map(run => run.finished_at ?? run.updated_at)
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;

  useEffect(() => {
    if (!noticeKey || !noticeAt) return;
    const remaining = Date.parse(noticeAt) + TERMINAL_NOTICE_MS - Date.now();
    if (remaining <= 0) return;
    const timer = setTimeout(() => setDismissedNoticeKey(noticeKey), remaining);
    return () => clearTimeout(timer);
  }, [noticeKey, noticeAt]);

  const message = !statusKnown ? null : startTimedOut
    ? watch?.execution_mode === 'local'
      ? 'The sync has not reported a status yet. Check the backend logs before starting another fetch.'
      : 'The job has not reported a status yet. Check its Azure execution logs before starting another fetch.'
    : watch && !requested
      ? watch.execution_mode === 'local'
        ? 'The backend accepted the fetch request. Waiting for the sync to start…'
        : 'Azure accepted the fetch request. Waiting for the job to start…'
      : displayed && (displayed.status === 'running' || showTerminalNotice) ? describe(displayed) : null;
  return {
    busy, message, statusKnown, statusError, lastUpdatedAt,
    failed: startTimedOut || displayed?.status === 'failed' || displayed?.status === 'stale',
    watchRun(accepted: CatalogueFetchAccepted) {
      setStartTimedOut(false);
      setWatch({ ...accepted, waitingSince: Date.now() });
    },
  };
}
