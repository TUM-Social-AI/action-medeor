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
  let timerId = 0;
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
    setTimeout(callback, delay) { assert.equal(delay, 5000); timers.set(++timerId, callback); return timerId; },
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
      async poll() {
        const callbacks = [...timers.values()]; timers.clear();
        callbacks.forEach(callback => callback()); await settle();
      },
      unmount() { slots.forEach(slot => slot?.cleanup?.()); },
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
  assert.equal(render().button('Fetch new data').props.disabled, true);
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

const run = (status, extra = {}) => ({
  id: 'run-1', execution_name: 'job-123', status,
  started_at: '2026-10-22T10:00:00Z', updated_at: '2026-10-22T10:01:00Z',
  finished_at: status === 'running' ? null : '2026-10-22T10:01:00Z',
  summary: { processed: 2, failed: 0, processing_enabled: true }, message: null, ...extra,
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
  let polls = 0, signal;
  const render = await screen({
    getCatalogueArticles: async () => [],
    getCatalogueFetchAvailability: async () => ({ enabled: true }),
    getCatalogueSyncStatus: async value => {
      polls++; signal = value;
      if (polls === 1) throw new Error('offline');
      return { runs: [] };
    },
  });
  render(); await settle(); let ui = render();
  assert.match(ui.html, /Retrying automatically/);
  await ui.poll(); ui = render();
  assert.doesNotMatch(ui.html, /Retrying automatically/);
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
