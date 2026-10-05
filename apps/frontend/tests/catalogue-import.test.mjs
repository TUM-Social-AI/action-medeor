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
class ApiError extends Error {
  constructor(message, status, details) { super(message); this.status = status; this.details = details; }
}
const helpers = await load('../src/features/catalogue/import.ts', { '../../api/http': { ApiError } });
const file = (name, size = 10) => ({ name, size });

test('ERP file validation requires both files and enforces CSV, empty and size rules', () => {
  const { validateCatalogFiles: validate, MAX_CSV_BYTES } = helpers;
  assert.match(validate(null, file('translations.csv')), /both/);
  assert.match(validate(file('articles.xlsx'), file('translations.csv')), /CSV/);
  assert.match(validate(file('articles.csv', 0), file('translations.csv')), /empty/);
  assert.match(validate(file('articles.csv'), file('translations.csv', MAX_CSV_BYTES + 1)), /25 MB/);
  assert.equal(validate(file('ARTICLES.CSV', MAX_CSV_BYTES), file('translations.csv')), null);
});

test('row-level backend validation errors have readable field names and messages', () => {
  assert.equal(helpers.catalogImportError(new ApiError('invalid', 422, {
    detail: [{ row: 4, field: 'Lagerbestand', message: 'Invalid quantity' }],
  })), 'Row 4: Lagerbestand: Invalid quantity');
  assert.equal(helpers.catalogImportError(new Error('Network failed')), 'Network failed');
});

test('upload uses the existing multipart contract and progress endpoint', async () => {
  const calls = [];
  const api = await load('../src/api/catalogue.ts', { './http': {
    requestJson: async (...args) => { calls.push(args); return {}; },
  } });
  const articles = new File(['articles'], 'Artikeldaten.csv');
  const translations = new File(['translations'], 'Artikelübersetzungen.csv');
  await api.importCatalogue(articles, translations);
  assert.equal(calls[0][0], '/api/v1/catalog-imports');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(await calls[0][1].body.get('article_data').text(), 'articles');
  assert.equal(await calls[0][1].body.get('article_translations').text(), 'translations');
  assert.equal(calls[0][1].headers, undefined);
  await api.getCatalogueEmbeddingStatus('id/with/slash');
  assert.equal(calls[1][0], '/api/v1/catalog-imports/id%2Fwith%2Fslash/embedding-status');
});

const imported = {
  import_id: 'import-1', idempotent_replay: false, inserted_items: 2,
  text_updated_items: 1, metadata_updated_items: 3, unchanged_items: 4,
  inventory_refreshed_items: 10, missing_items: 0, reactivated_items: 0,
  embedding_jobs_created: 3, warnings: ['Unexpected flag treated as unblocked'],
};
function find(node, predicate) {
  if (!React.isValidElement(node)) return null;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props.children)) {
    const found = find(child, predicate);
    if (found) return found;
  }
  return null;
}
async function harness(api) {
  const states = [], refs = [], effects = [], timers = new Map();
  let stateIndex = 0, refIndex = 0, effectIndex = 0, timerId = 0, refreshes = 0;
  const fakeReact = {
    ...React,
    useState: initial => {
      const index = stateIndex++;
      if (!(index in states)) states[index] = initial;
      return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }];
    },
    useRef: initial => {
      const index = refIndex++;
      return refs[index] ??= { current: index === 0 ? { showModal() {}, close() {} } : initial };
    },
    useEffect: (callback, dependencies) => {
      const index = effectIndex++;
      const previous = effects[index];
      if (!previous || dependencies.some((value, i) => value !== previous.dependencies[i])) {
        previous?.cleanup?.();
        effects[index] = { callback, dependencies, pending: true };
      }
    },
  };
  const { CatalogueImportDialog } = await load('../src/components/CatalogueImportDialog.tsx', {
    react: fakeReact, '../api/catalogue': api, '../features/catalogue/import': helpers,
  }, { setTimeout: (callback, delay) => { assert.equal(delay, 5000); timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => timers.delete(id) });
  function render() {
    stateIndex = refIndex = effectIndex = 0;
    const tree = CatalogueImportDialog({ onClose() {}, onUpdated() { refreshes++; } });
    for (const effect of effects) if (effect.pending) {
      effect.pending = false; effect.cleanup = effect.callback();
    }
    return tree;
  }
  function select(tree, label, value) {
    const heading = find(tree, node => node.type === 'label' && node.props.children[0].trim() === label);
    const input = find(tree, node => node.type === 'input' && node.props.id === heading.props.htmlFor);
    input.props.onChange({ target: { files: [value] } });
  }
  return { render, select, timers, get refreshes() { return refreshes; },
    close() { for (const effect of effects) effect.cleanup?.(); } };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('file controls have English labels and explicit choose-file buttons', async () => {
  const h = await harness({});
  const html = renderToStaticMarkup(h.render());
  assert.ok(html.includes('Article data'));
  assert.ok(html.includes('Article translations'));
  assert.equal((html.match(/>Choose file<\/button>/g) ?? []).length, 2);
  assert.equal((html.match(/No file selected/g) ?? []).length, 2);
  assert.ok(!html.includes('Datei auswählen'));
  h.close();
});

test('dialog uploads once, refreshes the catalogue and polls real progress until completion', async () => {
  let uploads = 0, polls = 0, resolveUpload;
  const h = await harness({
    importCatalogue: () => { uploads++; return new Promise(resolve => { resolveUpload = resolve; }); },
    getCatalogueEmbeddingStatus: async () => ({
      pending: polls++ === 0 ? 1 : 0, running: 0, completed: polls === 1 ? 2 : 3,
      failed: 0, configuration_error: null,
    }),
  });
  let tree = h.render();
  h.select(tree, 'Article data', file('articles.csv'));
  h.select(tree, 'Article translations', file('translations.csv'));
  tree = h.render();
  const submit = find(tree, node => node.type === 'form').props.onSubmit;
  submit({ preventDefault() {} }); submit({ preventDefault() {} });
  assert.equal(uploads, 1);
  assert.ok(renderToStaticMarkup(h.render()).includes('Uploading and updating…'));
  resolveUpload(imported);
  await tick(); h.render(); await tick();
  let html = renderToStaticMarkup(h.render());
  assert.ok(html.includes('ERP catalogue and inventory updated.'));
  assert.ok(html.includes('Inventory refreshed'));
  assert.ok(html.includes('Unexpected flag treated as unblocked'));
  assert.ok(html.includes('2 ready · 1 pending'));
  assert.equal(h.refreshes, 2);
  const poll = [...h.timers.values()][0]; h.timers.clear(); poll();
  await tick();
  html = renderToStaticMarkup(h.render());
  assert.ok(html.includes('Embedding processing complete.'));
  assert.equal(h.refreshes, 3);
  assert.equal(h.timers.size, 0);
  h.close();
});

test('failed uploads show errors without success or catalogue refresh', async () => {
  const h = await harness({ importCatalogue: async () => { throw new Error('Invalid export'); } });
  let tree = h.render();
  h.select(tree, 'Article data', file('articles.csv'));
  h.select(tree, 'Article translations', file('translations.csv'));
  tree = h.render();
  find(tree, node => node.type === 'form').props.onSubmit({ preventDefault() {} });
  await tick();
  const html = renderToStaticMarkup(h.render());
  assert.ok(html.includes('Invalid export'));
  assert.ok(!html.includes('ERP catalogue and inventory updated.'));
  assert.equal(h.refreshes, 0);
  h.close();
});

test('replay success stays separate from failed embeddings and temporary configuration errors', async () => {
  let polls = 0;
  const h = await harness({
    importCatalogue: async () => ({ ...imported, idempotent_replay: true }),
    getCatalogueEmbeddingStatus: async () => ({
      pending: 0, running: 0, completed: 2, failed: 1,
      configuration_error: polls++ === 0 ? 'No active embedding model is registered yet.' : null,
    }),
  });
  let tree = h.render();
  h.select(tree, 'Article data', file('articles.csv'));
  h.select(tree, 'Article translations', file('translations.csv'));
  tree = h.render();
  find(tree, node => node.type === 'form').props.onSubmit({ preventDefault() {} });
  await tick(); h.render(); await tick();
  let html = renderToStaticMarkup(h.render());
  assert.ok(html.includes('already imported'));
  assert.ok(html.includes('No active embedding model'));
  assert.equal(h.timers.size, 1);
  const poll = [...h.timers.values()][0]; h.timers.clear(); poll();
  await tick();
  html = renderToStaticMarkup(h.render());
  assert.ok(html.includes('Some embeddings failed'));
  assert.ok(html.includes('The catalogue update is saved'));
  assert.ok(!html.includes('Embedding processing complete'));
  assert.equal(h.timers.size, 0);
  h.close();
});

test('closing the dialog aborts progress requests and stops polling', async () => {
  let progressSignal, resolveProgress;
  const h = await harness({
    importCatalogue: async () => imported,
    getCatalogueEmbeddingStatus: (_, signal) => {
      progressSignal = signal;
      return new Promise(resolve => { resolveProgress = resolve; });
    },
  });
  let tree = h.render();
  h.select(tree, 'Article data', file('articles.csv'));
  h.select(tree, 'Article translations', file('translations.csv'));
  tree = h.render();
  find(tree, node => node.type === 'form').props.onSubmit({ preventDefault() {} });
  await tick(); h.render();
  h.close();
  assert.equal(progressSignal.aborted, true);
  resolveProgress({ pending: 1, running: 0, completed: 0, failed: 0, configuration_error: null });
  await tick();
  assert.equal(h.timers.size, 0);
});
