import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/features/catalogue/filtering.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const {
  DEFAULT_FILTERS, availableStatuses, changeSource, getCatalogueView, selectStatus, statusOf,
} = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

const today = '2026-10-03';
function article(id, overrides) {
  return Object.freeze({
    id, name: '', source: 'erp', vendor: 'Alpha', category: 'medicine', reference: id,
    stock: null, valid_until: null, ...overrides,
  });
}
const articles = Object.freeze([
  article('1', { name: 'Needle', stock: '12' }),
  article('2', { name: 'Bandage', stock: '0' }),
  article('3', { name: 'Needle holder', stock: '0.5', category: 'equipment' }),
  article('4', { name: 'Unknown instrument', category: 'equipment' }),
  article('5', { name: 'Needle offer', source: 'sharepoint', valid_until: today }),
  article('6', { name: 'Bandage offer', source: 'sharepoint', valid_until: '2026-10-02' }),
  article('7', { name: 'Holder', source: 'sharepoint', category: 'equipment', vendor: 'Gamma', valid_until: '2026-12-31' }),
  article('8', { name: 'Special chair', source: 'sharepoint', category: 'equipment', reference: 'quotation.xlsx' }),
]);
const view = (filters = {}) => getCatalogueView(articles, { ...DEFAULT_FILTERS, ...filters }, today);
const ids = result => result.rows.map(article => article.id);

test('initial counts partition the real rows into sources, categories, and statuses', () => {
  const result = view();
  assert.deepEqual(result.sourceCounts, { all: 8, erp: 4, sharepoint: 4 });
  assert.deepEqual(result.categoryCounts, { all: 8, Medicine: 4, Equipment: 4 });
  assert.deepEqual(result.statusCounts, {
    all: 8, 'in-stock': 2, 'out-of-stock': 1, valid: 2, expired: 1, unknown: 2,
  });
  assert.deepEqual(result.visibleSourceCounts, { erp: 4, sharepoint: 4 });
});

test('status selections replace one another and can always be cleared', () => {
  let filters = selectStatus(DEFAULT_FILTERS, 'in-stock');
  assert.deepEqual(ids(view(filters)), ['1', '3']);
  filters = selectStatus(filters, 'out-of-stock');
  assert.equal(filters.status, 'out-of-stock');
  assert.deepEqual(ids(view(filters)), ['2']);
  filters = selectStatus(filters, 'out-of-stock');
  assert.equal(filters.status, 'all');
  assert.equal(view(filters).rows.length, 8);
  assert.equal(selectStatus(selectStatus(filters, 'expired'), 'all').status, 'all');
});

test('source changes update statuses and reset the previous selection atomically', () => {
  const filters = { ...DEFAULT_FILTERS, source: 'erp', status: 'in-stock' };
  const offers = changeSource(filters, 'sharepoint');
  assert.equal(offers.status, 'all');
  assert.deepEqual(ids(view(offers)), ['5', '6', '7', '8']);
  assert.deepEqual(view(offers).statusCounts, {
    all: 4, 'in-stock': 0, 'out-of-stock': 0, valid: 2, expired: 1, unknown: 1,
  });
  assert.deepEqual(availableStatuses('erp'), ['in-stock', 'out-of-stock', 'unknown']);
  assert.deepEqual(availableStatuses('sharepoint'), ['valid', 'expired', 'unknown']);
  assert.equal(selectStatus(offers, 'in-stock'), offers);
  assert.equal(changeSource(filters, 'erp'), filters);
  assert.equal(changeSource(offers, 'all').status, 'all');
});

test('search updates every count and composes with source and category', () => {
  const result = view({ query: '  NEEDLE  ' });
  assert.deepEqual(ids(result), ['1', '3', '5']);
  assert.deepEqual(result.sourceCounts, { all: 3, erp: 2, sharepoint: 1 });
  assert.deepEqual(result.categoryCounts, { all: 3, Medicine: 2, Equipment: 1 });
  assert.deepEqual(result.statusCounts, {
    all: 3, 'in-stock': 2, 'out-of-stock': 0, valid: 1, expired: 0, unknown: 0,
  });
  const erp = view({ query: 'needle', source: 'erp', category: 'Medicine' });
  assert.deepEqual(ids(erp), ['1']);
  assert.deepEqual(erp.sourceCounts, { all: 2, erp: 1, sharepoint: 1 });
  assert.equal(erp.statusCounts.all, 1);
  assert.equal(erp.categoryCounts.Equipment, 1);
  assert.deepEqual(erp.visibleSourceCounts, { erp: 1, sharepoint: 0 });
});

test('facet counts preserve alternatives when another status or category is selected', () => {
  const result = view({ source: 'erp', status: 'in-stock', category: 'Equipment' });
  assert.deepEqual(ids(result), ['3']);
  assert.deepEqual(result.categoryCounts, { all: 2, Medicine: 1, Equipment: 1 });
  assert.deepEqual(result.statusCounts, {
    all: 2, 'in-stock': 1, 'out-of-stock': 0, valid: 0, expired: 0, unknown: 1,
  });
  assert.deepEqual(result.sourceCounts, { all: 4, erp: 2, sharepoint: 2 });
});

test('search finds supplier, ERP reference, offer filename, and displayed category', () => {
  assert.deepEqual(ids(view({ query: 'gamma' })), ['7']);
  assert.deepEqual(ids(view({ query: 'quotation.xlsx' })), ['8']);
  assert.deepEqual(ids(view({ query: '2' })), ['2']);
  assert.deepEqual(ids(view({ query: 'Equipment' })), ['3', '4', '7', '8']);
  const other = article('9', { category: 'unknown' });
  assert.deepEqual(getCatalogueView([other], { ...DEFAULT_FILTERS, query: 'Other' }, today).rows, [other]);
});

test('no matches and empty catalogues keep all counts at zero without discarding filters', () => {
  const filters = { ...DEFAULT_FILTERS, query: 'not present', source: 'erp', status: 'in-stock' };
  const result = view(filters);
  assert.deepEqual(ids(result), []);
  assert.deepEqual(result.categories, ['Equipment', 'Medicine']);
  for (const counts of [result.sourceCounts, result.statusCounts, result.categoryCounts, result.visibleSourceCounts]) {
    assert.ok(Object.values(counts).every(value => value === 0));
  }
  assert.equal(filters.status, 'in-stock');
  assert.equal(selectStatus(filters, 'in-stock').status, 'all');
  const empty = getCatalogueView([], DEFAULT_FILTERS, today);
  assert.deepEqual(empty.categories, []);
  assert.equal(empty.statusCounts.all, 0);
  assert.equal(empty.categoryCounts.all, 0);
  assert.equal(empty.sourceCounts.all, 0);
});

test('missing or malformed availability is unknown; valid-until includes the whole end date', () => {
  for (const stock of [null, '', ' ', 'NaN', 'Infinity', 'bad']) {
    assert.equal(statusOf(article('x', { stock }), today), 'unknown');
  }
  assert.equal(statusOf(article('x', { stock: '0' }), today), 'out-of-stock');
  assert.equal(statusOf(article('x', { stock: '0.01' }), today), 'in-stock');
  for (const valid_until of [null, '', 'bad', '2026-02-30', '2026-13-01']) {
    assert.equal(statusOf(article('x', { source: 'sharepoint', valid_until }), today), 'unknown');
  }
  const offer = article('x', { source: 'sharepoint', valid_until: today });
  assert.equal(statusOf(offer, today), 'valid');
  assert.equal(statusOf(offer, '2026-10-04'), 'expired');
});

test('counts agree with the result of selecting each option across filter combinations', () => {
  for (const source of ['all', 'erp', 'sharepoint']) {
    for (const category of ['all', 'Medicine', 'Equipment']) {
      for (const status of ['all', ...availableStatuses(source)]) {
        for (const query of ['', 'needle', 'gamma', 'not present']) {
          const filters = { source, category, status, query };
          const result = view(filters);
          assert.equal(result.statusCounts[status], result.rows.length);
          assert.equal(result.categoryCounts[category], result.rows.length);
          assert.equal(result.visibleSourceCounts.erp + result.visibleSourceCounts.sharepoint, result.rows.length);
          assert.equal(result.sourceCounts.erp + result.sourceCounts.sharepoint, result.sourceCounts.all);
          assert.equal(Object.values(result.statusCounts).reduce((sum, count) => sum + count, 0), result.statusCounts.all * 2);
          assert.equal(Object.values(result.categoryCounts).reduce((sum, count) => sum + count, 0), result.categoryCounts.all * 2);
          for (const nextStatus of ['all', ...availableStatuses(source)]) {
            assert.equal(view({ ...filters, status: nextStatus }).rows.length, result.statusCounts[nextStatus]);
          }
          for (const nextCategory of ['all', 'Medicine', 'Equipment']) {
            assert.equal(view({ ...filters, category: nextCategory }).rows.length, result.categoryCounts[nextCategory]);
          }
          for (const nextSource of ['all', 'erp', 'sharepoint']) {
            if (nextSource !== source || status === 'all') {
              assert.equal(view(changeSource(filters, nextSource)).rows.length, result.sourceCounts[nextSource]);
            }
          }
        }
      }
    }
  }
});
