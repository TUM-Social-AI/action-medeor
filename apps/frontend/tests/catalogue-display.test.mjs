import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
async function load(path, dependencies = {}, DateClass = Date) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  const exports = {};
  new Function('require', 'exports', 'Date', outputText)(
    name => dependencies[name] ?? require(name), exports, DateClass,
  );
  return exports;
}

const now = '2026-10-03T12:00:00Z';
class FixedDate extends Date {
  constructor(...args) { super(...(args.length ? args : [now])); }
}
const display = await load('../src/features/matching/offer-display.ts', {}, FixedDate);
const filtering = await load('../src/features/catalogue/filtering.ts');
const baseOffer = {
  id: 'offer:1', source: 'sharepoint', name: 'Test strips', vendor: 'Centramed',
  category: 'equipment', reference: 'offer.pdf', source_url: null, stock: null, unit: null,
  valid_until: null, offer_date: '2026-01-26T23:00:00Z', offer_date_source: 'document',
  offer_validity_source: null, price: '18.50', price_basis: '50 St.',
  unit_price: null, unit_price_unit: null, currency: 'EUR', embedded: true,
};

async function render(articles) {
  let stateIndex = 0;
  const { CatalogueScreen } = await load('../src/components/CatalogueScreen.tsx', {
    react: {
      ...React,
      useState: initial => [stateIndex++ === 0 ? articles : typeof initial === 'function' ? initial() : initial, () => {}],
      useEffect: () => {}, useMemo: callback => callback(),
    },
    '../api/catalogue': { getCatalogueArticles: () => { throw new Error('Unexpected fetch'); } },
    '../features/catalogue/filtering': filtering,
    '../features/matching/offer-display': display,
    '../features/matching/use-offer-date-refresh': { useOfferDateRefresh: () => {} },
  }, FixedDate);
  return renderToStaticMarkup(React.createElement(CatalogueScreen));
}

test('catalogue shows quoted pack prices and age without inferring validity', async () => {
  const html = await render([baseOffer]);
  assert.ok(html.includes(display.formatOfferPrice('18.50', 'EUR', '50 St.')));
  assert.ok(html.includes('Offer price'));
  assert.ok(html.includes('Offer is 8 months old'));
  assert.ok(html.includes('Validity unknown'));
  assert.ok(!html.includes('On request'));
  assert.ok(!html.includes('Valid until'));
});

test('catalogue prefers explicit unit prices, including zero, with their own unit', async () => {
  for (const unit_price of ['0.37', '0']) {
    const html = await render([{ ...baseOffer, unit_price, unit_price_unit: 'St.' }]);
    assert.ok(html.includes(display.formatOfferPrice('18.50', 'EUR', '50 St.', unit_price, 'St.')));
    assert.ok(html.includes('Unit price'));
    assert.ok(!html.includes(' / 50 St.'));
  }
});

test('catalogue preserves date provenance and explicit expiry precedence', async () => {
  const estimated = await render([{ ...baseOffer, offer_date_source: 'sharepoint_created' }]);
  assert.ok(estimated.includes('estimated from file creation'));
  const expired = await render([{ ...baseOffer, valid_until: '2026-10-02', offer_validity_source: 'relative_document' }]);
  assert.ok(expired.includes('Expired'));
  assert.ok(expired.includes('calculated from relative validity'));
  assert.ok(!expired.includes('months old'));
  const valid = await render([{ ...baseOffer, valid_until: '2026-10-03' }]);
  assert.ok(valid.includes('Valid until'));
  assert.ok(!valid.includes('Validity unknown'));
});

test('missing prices and dates have honest fallbacks; ERP keeps its stock display', async () => {
  const html = await render([
    { ...baseOffer, price: null, offer_date: null },
    { ...baseOffer, id: 'erp:123', source: 'erp', name: 'ERP item', stock: '12', unit: 'piece', price: null },
  ]);
  assert.ok(html.includes('On request'));
  assert.ok(html.includes('Offer date unknown'));
  assert.ok(html.includes('12 piece'));
  assert.ok(!html.includes('EUR'));
});
