import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
async function load(path, dependencies, timers = {}) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  new Function('require', 'exports', 'setTimeout', 'clearTimeout', outputText)(
    name => dependencies[name] ?? require(name), exports,
    timers.setTimeout ?? setTimeout, timers.clearTimeout ?? clearTimeout,
  );
  return exports;
}

const filtering = await load('../src/features/catalogue/filtering.ts', {});
const display = await load('../src/features/matching/offer-display.ts', {});
const settle = () => new Promise(resolve => setImmediate(resolve));
function find(node, predicate) {
  if (!React.isValidElement(node)) return null;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props.children)) {
    const found = find(child, predicate);
    if (found) return found;
  }
  return null;
}

async function screen(api) {
  const slots = [], effects = [], timers = new Map();
  let timerId = 0, timerNow = 0;
  async function advance(milliseconds) {
    const target = timerNow + milliseconds;
    while (true) {
      const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > target) break;
      const [id, timer] = next;
      timerNow = timer.at;
      timers.delete(id);
      timer.callback();
      await settle();
    }
    timerNow = target;
  }
  api = { getCatalogueSyncStatus: async () => ({ runs: [] }), ...api };
  let cursor = 0;
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useRef(initial) { return slots[cursor++] ??= { current: initial }; },
    useMemo(callback) { return callback(); },
    useEffect(callback, deps) {
      const index = cursor++;
      if (!slots[index] || deps.some((value, i) => value !== slots[index].deps[i])) {
        const previous = slots[index];
        slots[index] = { deps };
        effects.push(() => { previous?.cleanup?.(); slots[index].cleanup = callback(); });
      }
    },
  };
  const sync = await load('../src/features/catalogue/use-sync-status.ts', {
    react: hooks, '../../api/catalogue': api,
  }, {
    setTimeout(callback, delay) {
      assert.ok(delay > 0 && delay <= 8000);
      timers.set(++timerId, { callback, at: timerNow + delay });
      return timerId;
    },
    clearTimeout(id) { timers.delete(id); },
  });
  const { CatalogueScreen } = await load('../src/components/CatalogueScreen.tsx', {
    react: hooks, '../api/catalogue': api,
    './CatalogueImportDialog': { CatalogueImportDialog: () => null },
    '../features/catalogue/filtering': filtering,
    '../features/matching/offer-display': display,
    '../features/matching/use-offer-date-refresh': { useOfferDateRefresh() {} },
    '../features/catalogue/use-sync-status': sync,
  });
  return () => {
    cursor = 0;
    const tree = CatalogueScreen();
    effects.splice(0).forEach(effect => effect());
    return {
      html: renderToStaticMarkup(tree),
      button: label => find(tree, node => node.type === 'button' && renderToStaticMarkup(node).includes(label)),
      lastUpdated: find(tree, node => node.type === 'time'),
      poll: () => advance(5000),
      advance,
      unmount() {
        slots.forEach(slot => slot?.cleanup?.());
        assert.equal(timers.size, 0);
      },
    };
  };
}

test('local availability keeps fetching disabled with an explanation', async () => {
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: false, reason: 'Azure app only' }),
  });
  render(); await settle();
  const button = render().button('Fetch new data');
  assert.equal(button.props.disabled, true);
  assert.equal(button.props.title, 'Azure app only');
});

test('a click starts one job and waits for its database status', async () => {
  let starts = 0, loads = 0, accept;
  const render = await screen({
    getCatalogueArticles: async () => { loads++; return []; },
    getCatalogueFetchAvailability: async () => ({ enabled: true, reason: null }),
    startCatalogueFetch: () => { starts++; return new Promise(resolve => { accept = resolve; }); },
  });
  assert.equal(render().button('Checking fetch status…').props.disabled, true);
  await settle();
  const click = render().button('Fetch new data').props.onClick;
  click(); click();
  assert.equal(starts, 1);
  assert.equal(render().button('Starting fetch').props.disabled, true);
  accept({ status: 'accepted', execution_name: 'job-123', requested_at: new Date().toISOString() }); await settle();
  const accepted = render();
  assert.match(accepted.html, /Azure accepted the fetch request/);
  assert.match(accepted.html, /Waiting for the job to start/);
  accepted.button('Reload catalogue').props.onClick(); render();
  assert.equal(loads, 2);
});

test('local acceptance reports backend execution and never mentions an Azure job', async () => {
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    startCatalogueFetch: async () => ({
      status: 'accepted', execution_name: 'local-execution',
      execution_mode: 'local', requested_at: new Date().toISOString(),
    }),
  });
  render(); await settle();
  render().button('Fetch new data').props.onClick(); await settle();
  let ui = render(); await settle(); ui = render();
  assert.match(ui.html, /The backend accepted the fetch request/);
  assert.doesNotMatch(ui.html, /Azure/);
  assert.equal(ui.button('Fetching…').props.disabled, true);
  ui.unmount();
});

const run = (status, extra = {}) => ({
  id: 'run-1', execution_name: 'job-123', status,
  started_at: '2026-10-22T10:00:00Z', updated_at: '2026-10-22T10:01:00Z',
  finished_at: status === 'running' ? null : new Date(Date.now()).toISOString(),
  summary: { processed: 2, failed: 0, processing_enabled: true }, message: null, ...extra,
});

for (const status of ['running', 'idle']) {
  test(`fetching waits for delayed initial status before confirming ${status}`, async () => {
    let reportStatus, starts = 0;
    const render = await screen({
      getCatalogueArticles: async () => [],
      getCatalogueFetchAvailability: async () => ({ enabled: true }),
      getCatalogueSyncStatus: () => new Promise(resolve => { reportStatus = resolve; }),
      startCatalogueFetch: async () => { starts++; },
    });
    let ui = render();
    assert.equal(ui.button('Checking fetch status…').props.disabled, true);
    await settle();
    ui = render();
    const checking = ui.button('Checking fetch status…');
    assert.equal(checking.props.disabled, true);
    checking.props.onClick();
    assert.equal(starts, 0);

    reportStatus({ runs: status === 'running' ? [run('running')] : [] });
    await settle();
    ui = render();
    const button = ui.button(status === 'running' ? 'Fetching…' : 'Fetch new data');
    assert.equal(button.props.disabled, status === 'running');
    if (status === 'running') {
      button.props.onClick();
      assert.equal(starts, 0);
    }
    ui.unmount();
  });
}

test('background polling retains known status and blocks fetching after an error until recovery', async () => {
  let polls = 0, starts = 0, rejectStatus, reportStatus;
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: () => {
      polls++;
      if (polls === 1) return Promise.resolve({ runs: [] });
      return new Promise((resolve, reject) => { reportStatus = resolve; rejectStatus = reject; });
    },
    startCatalogueFetch: async () => { starts++; },
  });
  render(); await settle();
  let ui = render();
  assert.equal(ui.button('Fetch new data').props.disabled, false);

  await ui.poll();
  ui = render();
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  rejectStatus(new Error('offline'));
  await settle();
  ui = render();
  assert.match(ui.html, /Retrying automatically/);
  assert.equal(ui.button('Fetch status unavailable').props.disabled, true);
  ui.button('Fetch status unavailable').props.onClick();
  assert.equal(starts, 0);

  await ui.poll();
  ui = render();
  assert.equal(ui.button('Fetch status unavailable').props.disabled, true);
  ui.button('Fetch status unavailable').props.onClick();
  assert.equal(starts, 0);
  reportStatus({ runs: [] });
  await settle();
  ui = render();
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  assert.doesNotMatch(ui.html, /Retrying automatically/);
  ui.unmount();
});

test('unknown fetch status hides the previous job error until a confirmed result is available', async () => {
  let polls = 0;
  const failed = run('failed', { message: 'Some documents or embeddings failed. Check the job logs.' });
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => {
      polls++;
      if (polls === 2) throw new Error('offline');
      return { runs: polls === 1 ? [failed] : [run('failed', { id: 'confirmed-failure', message: failed.message })] };
    },
  });
  render(); await settle();
  let ui = render();
  assert.match(ui.html, /Some documents or embeddings failed/);
  assert.doesNotMatch(ui.html, /Could not read fetch status/);

  await ui.poll(); ui = render();
  assert.match(ui.html, /Could not read fetch status. Retrying automatically/);
  assert.doesNotMatch(ui.html, /Some documents or embeddings failed|role="alert"|Reload catalogue/);
  assert.equal(ui.button('Fetch status unavailable').props.disabled, true);

  await ui.poll(); ui = render();
  assert.doesNotMatch(ui.html, /Could not read fetch status/);
  assert.match(ui.html, /Some documents or embeddings failed/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  ui.unmount();
});

test('scheduled completion refreshes the catalogue once and enables fetching', async () => {
  let runs = [run('running')], loads = 0;
  const render = await screen({
    getCatalogueArticles: async () => { loads++; return []; },
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs }),
  });
  render(); await settle();
  let ui = render();
  assert.equal(ui.button('Fetching…').props.disabled, true);
  runs = [run('completed')];
  await ui.poll(); render(); await settle();
  ui = render();
  assert.match(ui.html, /2 documents processed/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  assert.equal(loads, 2);
  await ui.poll(); render();
  assert.equal(loads, 2);
});

test('completion notices disappear after eight seconds and polling does not bring them back', async () => {
  let runs = [run('completed')];
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs: runs.map(value => ({ ...value })) }),
  });
  render(); await settle();
  let ui = render();
  assert.match(ui.html, /Fetch completed/);
  assert.match(ui.html, /Last updated/);
  assert.equal(ui.lastUpdated.props.dateTime, runs[0].finished_at);

  await ui.advance(8000);
  ui = render();
  assert.doesNotMatch(ui.html, /Fetch completed|Reload catalogue/);
  assert.match(ui.html, /Last updated/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  await ui.poll();
  ui = render();
  assert.doesNotMatch(ui.html, /Fetch completed|Reload catalogue/);

  runs = [run('running', { id: 'next-run' })];
  await ui.poll(); ui = render();
  assert.match(ui.html, /Fetching new data from SharePoint/);
  runs = [run('completed', { id: 'next-run' })];
  await ui.poll(); ui = render();
  assert.match(ui.html, /Fetch completed/);
  await ui.advance(8000); ui = render();
  assert.doesNotMatch(ui.html, /Fetch completed|Reload catalogue/);
  ui.unmount();
});

test('older completions show only the last successful update time on page load', async () => {
  const finishedAt = '2026-10-01T10:01:00Z';
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs: [run('completed', { finished_at: finishedAt })] }),
  });
  render(); await settle();
  const ui = render();
  assert.doesNotMatch(ui.html, /Fetch completed|Reload catalogue/);
  assert.match(ui.html, /Last updated/);
  assert.equal(ui.lastUpdated.props.dateTime, finishedAt);
  ui.unmount();
});

test('failed run notices expire and preserve the last successful update time', async () => {
  const finishedAt = '2026-10-01T10:01:00Z';
  let runs = [run('failed'), run('completed', { id: 'previous-run', finished_at: finishedAt })];
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs: runs.map(value => ({ ...value })) }),
  });
  render(); await settle();
  let ui = render();
  assert.match(ui.html, /SharePoint fetch failed/);
  assert.match(ui.html, /role="alert"/);
  await ui.advance(8000); ui = render();
  assert.doesNotMatch(ui.html, /SharePoint fetch failed|role="alert"|Reload catalogue/);
  assert.equal(ui.lastUpdated.props.dateTime, finishedAt);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  await ui.poll(); ui = render();
  assert.doesNotMatch(ui.html, /SharePoint fetch failed|role="alert"/);

  runs = [run('failed', { id: 'new-failure' }), runs[1]];
  await ui.poll(); ui = render();
  assert.match(ui.html, /SharePoint fetch failed/);
  assert.equal(ui.lastUpdated.props.dateTime, finishedAt);
  ui.unmount();
});

for (const status of ['failed', 'stale', 'skipped']) {
  test(`old ${status} notices stay hidden on page load and after polling`, async () => {
    const render = await screen({
      getCatalogueArticles: async () => [],
      getCatalogueFetchAvailability: async () => ({ enabled: true }),
      getCatalogueSyncStatus: async () => ({ runs: [run(status, {
        finished_at: status === 'stale' ? null : '2026-10-01T10:01:00Z',
        updated_at: '2026-10-01T10:01:00Z',
      })] }),
    });
    render(); await settle();
    let ui = render();
    assert.doesNotMatch(ui.html, /role="alert"|Reload catalogue|Last updated/);
    assert.equal(ui.button('Fetch new data').props.disabled, false);
    await ui.poll(); ui = render();
    assert.doesNotMatch(ui.html, /role="alert"|Reload catalogue/);
    ui.unmount();
  });
}

test('a run can show a fresh completion notice after its stale notice expires', async () => {
  let runs = [run('stale')];
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs }),
  });
  render(); await settle();
  let ui = render();
  assert.match(ui.html, /stopped reporting progress/);
  await ui.advance(8000); ui = render();
  assert.doesNotMatch(ui.html, /stopped reporting progress/);
  runs = [run('completed')];
  await ui.poll(); ui = render();
  assert.match(ui.html, /Fetch completed/);
  ui.unmount();
});

test('budget-only pauses show informational saved progress and allow another fetch', async () => {
  for (const count of [1, 2]) {
    const render = await screen({
      getCatalogueArticles: async () => [],
      getCatalogueFetchAvailability: async () => ({ enabled: true }),
      getCatalogueSyncStatus: async () => ({ runs: [run('completed', {
        summary: { processed: 0, failed: 0, turns: 5, deferred: count },
      })] }),
    });
    render(); await settle();
    const ui = render();
    assert.match(ui.html, /role="status"/);
    assert.doesNotMatch(ui.html, /role="alert"/);
    assert.match(ui.html, /Processing budget reached/);
    assert.ok(ui.html.includes(`Progress saved for ${count} unfinished document${count === 1 ? '' : 's'}.`));
    assert.match(ui.html, /Processing will continue on a later sync/);
    assert.equal(ui.button('Fetch new data').props.disabled, false);
    ui.unmount();
  }
});

test('a later completed run clears an earlier budget pause message', async () => {
  let runs = [run('completed', { summary: { processed: 0, deferred: 1, turns: 5 } })];
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs }),
  });
  render(); await settle();
  let ui = render();
  assert.match(ui.html, /Processing budget reached/);
  runs = [run('completed', { id: 'continued-run', summary: { processed: 1, deferred: 0, turns: 1 } })];
  await ui.poll(); render(); await settle();
  ui = render();
  assert.match(ui.html, /Fetch completed/);
  assert.doesNotMatch(ui.html, /budget reached|unfinished document/);
  ui.unmount();
});

test('mixed failures and budget pauses remain an error with the saved-progress explanation', async () => {
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs: [run('failed', {
      summary: { processed: 1, failed: 1, deferred: 1, turns: 5 },
      message: 'Some documents or embeddings failed. Processing budget reached. Progress saved for 1 unfinished document. Processing will continue on a later sync.',
    })] }),
  });
  render(); await settle();
  const ui = render();
  assert.match(ui.html, /role="alert"/);
  assert.match(ui.html, /Some documents or embeddings failed/);
  assert.match(ui.html, /Progress saved for 1 unfinished document/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  ui.unmount();
});

test('a different execution cannot complete the requested fetch', async () => {
  let runs = [];
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs }),
    startCatalogueFetch: async () => ({ status: 'accepted', execution_name: 'job-123', requested_at: '2026-10-22T09:59:00Z' }),
  });
  render(); await settle(); render().button('Fetch new data').props.onClick(); await settle();
  let ui = render(); await settle();
  runs = [run('completed', { id: 'other', execution_name: 'other-job' })];
  await ui.poll(); ui = render();
  assert.match(ui.html, /Waiting for the job/);
  runs.push(run('completed'));
  await ui.poll(); render(); await settle(); ui = render();
  assert.match(ui.html, /Fetch completed/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
});

test('a failed or stale run is visible and does not keep the button disabled', async () => {
  for (const status of ['failed', 'stale']) {
    const render = await screen({
      getCatalogueArticles: async () => [],
      getCatalogueFetchAvailability: async () => ({ enabled: true }),
      getCatalogueSyncStatus: async () => ({ runs: [run(status)] }),
    });
    render(); await settle(); const ui = render();
    assert.match(ui.html, /role="alert"/);
    assert.equal(ui.button('Fetch new data').props.disabled, false);
  }
});

test('poll errors retry and unmount aborts pending reads', async () => {
  let polls = 0, starts = 0, signal;
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async value => {
      polls++; signal = value;
      if (polls === 1) throw new Error('offline');
      return { runs: [] };
    },
    startCatalogueFetch: async () => { starts++; },
  });
  render(); await settle(); let ui = render();
  assert.match(ui.html, /Retrying automatically/);
  assert.equal(ui.button('Fetch status unavailable').props.disabled, true);
  ui.button('Fetch status unavailable').props.onClick();
  assert.equal(starts, 0);
  await ui.poll(); ui = render();
  assert.doesNotMatch(ui.html, /Retrying automatically/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
  assert.equal(polls, 2);
  ui.unmount();
  assert.equal(signal.aborted, true);
});

test('a job that never starts times out visibly and can still report later', async () => {
  const originalNow = Date.now;
  let now = Date.parse('2026-10-22T09:59:00Z'), runs = [];
  Date.now = () => now;
  try {
    const render = await screen({
      getCatalogueArticles: async () => [],
      getCatalogueFetchAvailability: async () => ({ enabled: true }),
      getCatalogueSyncStatus: async () => ({ runs }),
      startCatalogueFetch: async () => ({ status: 'accepted', execution_name: 'job-123', requested_at: '2026-10-22T09:59:00Z' }),
    });
    render(); await settle(); render().button('Fetch new data').props.onClick(); await settle();
    render(); await settle(); let ui = render();
    now += 301000;
    await ui.poll(); ui = render();
    assert.match(ui.html, /has not reported a status/);
    assert.equal(ui.button('Fetch new data').props.disabled, false);
    runs = [run('running')];
    await ui.poll(); ui = render();
    assert.doesNotMatch(ui.html, /has not reported a status/);
    assert.equal(ui.button('Fetching…').props.disabled, true);
  } finally {
    Date.now = originalNow;
  }
});

test('asynchronous acceptance ignores old runs and watches a subsequently reported sync', async () => {
  let runs = [run('completed', { id: 'old-run' })];
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async () => ({ runs }),
    startCatalogueFetch: async () => ({ status: 'accepted', execution_name: null, requested_at: '2026-10-22T10:05:00Z' }),
  });
  render(); await settle(); render().button('Fetch new data').props.onClick(); await settle();
  render(); await settle(); let ui = render();
  assert.match(ui.html, /Waiting for the job to start/);
  runs = [run('running', { started_at: '2026-10-22T10:06:00Z' })];
  await ui.poll(); ui = render();
  assert.match(ui.html, /Fetching new data from SharePoint/);
  runs = [run('completed', { started_at: '2026-10-22T10:06:00Z', summary: { processing_enabled: false } })];
  await ui.poll(); render(); await settle(); ui = render();
  assert.match(ui.html, /Offer processing is disabled/);
  assert.equal(ui.button('Fetch new data').props.disabled, false);
});

test('start failures are visible without reporting acceptance', async () => {
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true, reason: null }),
    startCatalogueFetch: async () => { throw new Error('Check managed identity permissions'); },
  });
  render(); await settle();
  render().button('Fetch new data').props.onClick(); await settle();
  const failed = render();
  assert.match(failed.html, /role="alert"[^>]*>Check managed identity permissions/);
  assert.doesNotMatch(failed.html, /Azure accepted/);
  assert.equal(failed.button('Fetch new data').props.disabled, false);
});

test('fetch client uses the backend POST and a CSRF-protecting header', async () => {
  const calls = [];
  const api = await load('../src/api/catalogue.ts', {
    './http': { requestJson: async (...args) => { calls.push(args); } },
  });
  await api.startCatalogueFetch();
  assert.deepEqual(calls, [['/api/v1/catalogue/fetch', {
    method: 'POST', headers: { 'X-Catalogue-Fetch': 'true' },
  }]]);
});
