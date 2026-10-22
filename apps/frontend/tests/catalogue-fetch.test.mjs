import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
async function load(path, dependencies) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  new Function('require', 'exports', outputText)(name => dependencies[name] ?? require(name), exports);
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
  const slots = [], effects = [];
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
      if (!slots[index] || deps.some((value, i) => value !== slots[index][i])) {
        slots[index] = deps;
        effects.push(callback);
      }
    },
  };
  const { CatalogueScreen } = await load('../src/components/CatalogueScreen.tsx', {
    react: hooks, '../api/catalogue': api,
    './CatalogueImportDialog': { CatalogueImportDialog: () => null },
    '../features/catalogue/filtering': filtering,
    '../features/matching/offer-display': display,
    '../features/matching/use-offer-date-refresh': { useOfferDateRefresh() {} },
  });
  return () => {
    cursor = 0;
    const tree = CatalogueScreen();
    effects.splice(0).forEach(effect => effect());
    return {
      html: renderToStaticMarkup(tree),
      button: label => find(tree, node => node.type === 'button' && renderToStaticMarkup(node).includes(label)),
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

test('a click starts one job, waits for acceptance, and offers catalogue reload', async () => {
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
  accept({ status: 'accepted', execution_name: 'job-123' }); await settle();
  const accepted = render();
  assert.match(accepted.html, /Azure accepted the fetch request/);
  assert.match(accepted.html, /background/);
  accepted.button('Reload catalogue').props.onClick(); render();
  assert.equal(loads, 2);
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
