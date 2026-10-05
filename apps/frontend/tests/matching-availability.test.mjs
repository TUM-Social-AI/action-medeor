import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
async function load(path, dependencies = {}) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  new Function('require', 'exports', outputText)(name => dependencies[name] ?? require(name), exports);
  return exports;
}
const display = await load('../src/features/matching/availability-display.ts');
const { CandidateAvailability } = await load('../src/components/CandidateAvailability.tsx', {
  '../features/matching/availability-display': display,
});
const candidate = { available_quantity: '50', stock_unit: 'PAKET', availability_status: 'unknown' };

test('known ERP quantity stays visible when conversion to the request is unknown', () => {
  const html = renderToStaticMarkup(React.createElement(CandidateAvailability, { candidate }));
  assert.ok(html.includes('50 PAKET'));
  assert.ok(html.includes('Request quantity not comparable'));
  assert.ok(html.includes('text-gray-500'));
  assert.ok(!html.includes('on hand'));
});

test('stock quantity and request coverage are separate, including zero stock', () => {
  assert.deepEqual(display.getCandidateAvailability({ ...candidate, availability_status: 'on_hand_sufficient' }), {
    quantity: '50 PAKET', coverage: 'Covers requested quantity',
    tone: 'green',
  });
  assert.deepEqual(display.getCandidateAvailability({ ...candidate, available_quantity: 0, availability_status: 'procurement_indicated' }), {
    quantity: '0 PAKET', coverage: 'Additional stock needed',
    tone: 'red',
  });
});

test('quantity colors distinguish insufficient stock, a narrow margin, and ample stock', () => {
  for (const [available, status, expected] of [
    [95, 'on_hand_partial', 'red'],
    [100, 'on_hand_sufficient', 'orange'],
    [110, 'on_hand_sufficient', 'orange'],
    [111, 'on_hand_sufficient', 'green'],
  ]) {
    const input = { ...candidate, available_quantity: available, required_stock_quantity: '100', availability_status: status };
    assert.equal(display.getCandidateAvailability(input).tone, expected);
    const html = renderToStaticMarkup(React.createElement(CandidateAvailability, { candidate: input }));
    assert.ok(html.includes(`text-${expected}-700`));
    assert.ok(html.includes(`${available} PAKET</span>`));
    assert.ok(!html.includes('>Covers requested quantity'));
    assert.ok(!html.includes('on hand'));
  }
});

test('margin uses the request expressed in stock units after a confirmed conversion', () => {
  const input = { ...candidate, available_quantity: '5', required_stock_quantity: String(55 / 12), availability_status: 'on_hand_sufficient' };
  assert.equal(display.getCandidateAvailability(input).tone, 'orange');
  assert.equal(display.getCandidateAvailability({ ...input, required_stock_quantity: String(50 / 12) }).tone, 'green');
  assert.equal(display.getCandidateAvailability({ ...input, required_stock_quantity: '0' }).tone, 'green');
});

test('legacy and invalid quantities never become fabricated inventory', () => {
  for (const value of [null, undefined, '', 'not-a-number', '-1']) {
    assert.equal(display.getCandidateAvailability({ ...candidate, available_quantity: value }).quantity, null);
  }
  assert.equal(display.getCandidateAvailability({ ...candidate, stock_unit: null }).quantity, '50 (unit unknown)');
  const html = renderToStaticMarkup(React.createElement(CandidateAvailability, { candidate: { ...candidate, available_quantity: null } }));
  assert.ok(html.includes('Quantity unavailable'));
  assert.ok(!html.includes('50 PAKET'));
});
