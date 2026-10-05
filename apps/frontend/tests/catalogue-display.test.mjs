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
      useState: initial => {
        const index = stateIndex++;
        return [index === 0 ? articles : typeof initial === 'function' ? initial() : initial, () => {}];
      },
      useEffect: () => {}, useMemo: callback => callback(),
    },
    './CatalogueImportDialog': { CatalogueImportDialog: () => null },
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

test('ERP updates and future SharePoint fetching have separate controls', async () => {
  const html = await render([]);
  assert.match(html, /<button[^>]*>[^]*?Update ERP catalogue<\/button>/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>[^]*?Fetch new data<\/button>/);
});

test('restricted articles remain visible; Stammartikel replaces misleading stock', async () => {
  const html = await render([
    { ...baseOffer, id: 'erp:1', source: 'erp', name: 'Restricted', stock: '12', on_hand: '12', unit: 'piece',
      blocked: true, sales_blocked: true, purchasing_blocked: true },
    { ...baseOffer, id: 'erp:2', source: 'erp', name: 'Base article', stock: '0', unit: 'piece', master_item: true },
  ]);
  assert.ok(html.includes('Restricted'));
  assert.ok(html.includes('Suspended'));
  assert.ok(html.includes('Sales blocked'));
  assert.ok(html.includes('Purchasing blocked'));
  assert.ok(html.includes('12 piece'));
  assert.ok(html.includes('Stammartikel'));
  assert.ok(!html.includes('0 piece'));
});

test('database-backed suspension shows the mockup design and available stock without unsupported notes', async () => {
  const html = await render([{
    ...baseOffer, id: 'erp:ERP-51108', source: 'erp', name: 'Infusion Set 20 drops/ml, Luer Lock',
    reference: 'ERP-51108', vendor: 'FlowMed GmbH', stock: '320', on_hand: '340', unit: 'pcs',
    blocked: true, suspension_reason: 'Replaced by successor ERP-51190',
    suspension_by: 'Procurement',
  }]);
  assert.ok(html.includes('repeating-linear-gradient'));
  assert.ok(html.includes('[border-left-style:dashed]'));
  assert.ok(html.includes('SUSPENDED'));
  assert.ok(!html.includes('Replaced by successor ERP-51190'));
  assert.ok(!html.includes('Suspended by Procurement'));
  assert.ok(html.includes('Excluded from matching'));
  assert.ok(!html.includes('since '));
  assert.ok(html.includes('320 pcs available'));
  assert.ok(!html.includes('340 pcs'));
  assert.ok(!html.includes('on hand'));
  assert.ok(html.includes('line-through decoration-slate-300'));
  assert.ok(!html.includes('Show suspended example'));
  assert.ok(!html.includes('Example only'));
  assert.match(html, />1<\/strong> matching articles/);
});

test('purchasing-only restrictions describe conditional matching and legacy metadata stays usable', async () => {
  const html = await render([{
    ...baseOffer, id: 'erp:1', source: 'erp', name: 'Purchase restricted',
    blocked: false, purchasing_blocked: true, on_hand: '60', stock: '50', unit: 'PAKET',
  }]);
  assert.ok(html.includes('Stock-only matching'));
  assert.equal((html.match(/50 PAKET available/g) ?? []).length, 1);
  assert.ok(!html.includes('60 PAKET'));
  assert.ok(!html.includes('on hand'));
  assert.ok(!html.includes('full requests only'));
  assert.ok(!html.includes('Excluded from matching'));
  assert.ok(!html.includes('since '));
  const unknown = await render([{
    ...baseOffer, id: 'erp:2', source: 'erp', name: 'Suspended without metadata', blocked: true,
    on_hand: '60', stock: null,
  }]);
  assert.ok(unknown.includes('Excluded from matching'));
  assert.ok(unknown.includes('Stock unavailable'));
  assert.ok(!unknown.includes('60 '));
  assert.ok(!unknown.includes('Invalid Date'));
});
