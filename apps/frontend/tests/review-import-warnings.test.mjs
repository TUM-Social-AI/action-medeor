import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = await readFile(new URL('../src/components/ReviewItemsScreen.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX },
});
const exports = {};
new Function('require', 'exports', outputText)(name => {
  if (name === '../api/client') return {};
  if (name === './ScreenState' || name === './WorkflowStepper') {
    return { ErrorPanel: () => null, LoadingPanel: () => null, WorkflowStepper: () => null };
  }
  return require(name);
}, exports);

const data = {
  requestId: 'import-test', source: { fileName: 'request.xlsx', rowsDetected: 0, partner: '' },
  partner: { partner: '', region: '', requestId: 'import-test', contact: '', confirmed: false },
  items: [], sourceReferences: [], counts: { total: 0, verified: 0, needsReview: 0, lowConfidence: 0, missing: 0 },
  attributeColumns: [], columnLabels: {}, availableColumns: [],
};
function render(initialData) {
  return renderToStaticMarkup(React.createElement(exports.ReviewItemsScreen, {
    requestId: 'import-test', initialData, onContinue: () => {},
  }));
}

test('uncertain import warnings reach the review screen', () => {
  const html = render({ ...data, parserWarnings: ['Columns could not be confirmed; review basic extraction'] });
  assert.match(html, /role="status"/);
  assert.match(html, /Columns could not be confirmed/);
});

test('older review responses and clean imports render without a warning panel', () => {
  assert.doesNotMatch(render(data), /Import notes/);
  assert.doesNotMatch(render({ ...data, parserWarnings: [] }), /Import notes/);
});

test('AI checked rows show inference provenance and need no individual verification', () => {
  const html = render({ ...data, items: [{
    id: 1, name: 'Diagnostic scanner', quantity: 2, unit: 'pcs', notes: '', itemNumber: '', shelfLife: '',
    attributes: {}, priority: 'medium', confidence: 95, status: 'verified', domain: 'equipment', manual: false,
    verificationSource: 'ai', inferredFields: { type: 'Diagnostic scanner', unit: 'Diagnostic scanner' }, reviewReasons: [],
  }], reviewSummary: { status: 'completed', checked: 1, corrected: 1, unresolved: 0 } });
  assert.match(html, /AI checked/);
  assert.doesNotMatch(html, /AI inferred/);
  assert.match(html, /95%/);
  assert.match(html, /1 rows AI checked/);
  assert.match(html, /0 unresolved/);
  assert.doesNotMatch(html, /Review with AI/);
  assert.doesNotMatch(html, /Review Required/);
  assert.doesNotMatch(html, /require manual review before/);
});

test('supplier column notes are informational and provider failures remain visible', () => {
  const html = render({ ...data, parserWarnings: ['Ignored supplier/admin columns: Price'],
    reviewSummary: { status: 'unavailable', checked: 0, message: 'Some rows could not be AI checked. Basic extraction has been retained; you can retry.' } });
  assert.match(html, /Source column notes/);
  assert.doesNotMatch(html, /Import notes/);
  assert.match(html, /Basic extraction has been retained/);
});

test('unresolved row issues are shown next to the source item', () => {
  const html = render({ ...data, items: [{
    id: 1, name: 'Antibiotic', quantity: 2, unit: '', notes: '', itemNumber: '', shelfLife: '',
    attributes: {}, priority: 'medium', confidence: null, status: 'needs_review', domain: 'medicine', manual: false,
    reviewReasons: ['Medicine packaging is unclear'],
  }] });
  assert.match(html, /Medicine packaging is unclear/);
  assert.match(html, /Review Required/);
});


test('inferred details identify field values rather than repeating source evidence', () => {
  const html = renderToStaticMarkup(React.createElement(exports.InferredFieldsDetails, { item: {
    domain: 'equipment', unit: 'pcs', inferredFields: {
      type: 'Blood and IV infusion Warmer', unit: 'Blood and IV infusion Warme',
    },
  }}));
  assert.match(html, /Type:/);
  assert.match(html, /Equipment/);
  assert.match(html, /Unit:/);
  assert.match(html, /pcs/);
  assert.match(html, /AI inferred/);
  assert.doesNotMatch(html, /Blood and IV/);
});

test('AI review locks the application while pending and removes the button after success', async () => {
  const slots = [];
  let cursor = 0;
  let effects = [];
  let resolveReview;
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useRef(initial) { return hooks.useState(() => ({ current: initial }))[0]; },
    useMemo(callback) { return callback(); },
    useEffect(callback, dependencies) {
      const index = cursor++;
      const previous = slots[index];
      if (!previous || dependencies.some((value, i) => value !== previous.dependencies[i])) {
        slots[index] = { dependencies, cleanup: previous?.cleanup };
        effects.push(() => { previous?.cleanup?.(); slots[index].cleanup = callback(); });
      }
    },
  };
  const interactive = {};
  new Function('require', 'exports', outputText)(name => {
    if (name === 'react') return hooks;
    if (name === 'react-dom') return { createPortal: element => element };
    if (name === '../api/client') return { reviewWithAi: () => new Promise(resolve => { resolveReview = resolve; }) };
    if (name === './ScreenState' || name === './WorkflowStepper') return { ErrorPanel: () => null, LoadingPanel: () => null, WorkflowStepper: () => null };
    return require(name);
  }, interactive);
  const attributes = new Set();
  const appRoot = { hasAttribute: name => attributes.has(name), setAttribute: name => attributes.add(name), removeAttribute: name => attributes.delete(name) };
  const priorDocument = globalThis.document;
  const priorHTMLElement = globalThis.HTMLElement;
  globalThis.HTMLElement = class {};
  globalThis.document = { body: {}, activeElement: null, getElementById: () => appRoot };
  function renderTree() {
    cursor = 0;
    effects = [];
    const tree = interactive.ReviewItemsScreen({ requestId: 'import-test', initialData: data, onContinue: () => {} });
    for (const effect of effects) effect();
    return tree;
  }
  function findButton(tree) {
    if (!tree || typeof tree !== 'object') return null;
    if (Array.isArray(tree)) return tree.map(findButton).find(Boolean);
    if (tree.type === 'button' && tree.props.children === 'Review with AI') return tree;
    return findButton(tree.props?.children);
  }
  try {
    const button = findButton(renderTree());
    assert.ok(button);
    button.props.onClick();
    const pending = renderTree();
    assert.equal(attributes.has('inert'), true);
    const pendingHtml = renderToStaticMarkup(pending);
    assert.match(pendingHtml, /role="dialog"/);
    assert.match(pendingHtml, /aria-modal="true"/);
    assert.match(pendingHtml, /Checking items with AI/);
    resolveReview({ ...data, reviewSummary: { status: 'completed', checked: 0, corrected: 0, unresolved: 0 } });
    await Promise.resolve();
    const finished = renderTree();
    assert.equal(attributes.has('inert'), false);
    assert.equal(findButton(finished), undefined);
    assert.doesNotMatch(renderToStaticMarkup(finished), /Checking items with AI/);
  } finally {
    globalThis.document = priorDocument;
    globalThis.HTMLElement = priorHTMLElement;
  }
});
