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
    attributes: {}, priority: 'medium', confidence: null, status: 'verified', domain: 'equipment', manual: false,
    verificationSource: 'ai', inferredFields: { type: 'Diagnostic scanner', unit: 'Diagnostic scanner' }, reviewReasons: [],
  }], reviewSummary: { status: 'completed', checked: 1, corrected: 1, unresolved: 0 } });
  assert.match(html, /AI checked/);
  assert.match(html, /AI inferred/);
  assert.match(html, /1 rows AI checked/);
  assert.match(html, /0 unresolved/);
  assert.match(html, /Review with AI/);
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
