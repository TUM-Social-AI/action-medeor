import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/features/matching/offer-display.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { getOfferStatus, berlinDay } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const now = new Date('2026-10-02T12:00:00Z');

test('offers remain valid through their end date, then become expired', () => {
  const today = getOfferStatus({ offer_valid_until: '2026-10-02' }, now);
  assert.equal(today.expired, false);
  assert.equal(today.muted, false);
  assert.equal(today.badge, null);
  const yesterday = getOfferStatus({ offer_valid_until: '2026-10-01' }, now);
  assert.equal(yesterday.expired, true);
  assert.equal(yesterday.muted, true);
  assert.equal(yesterday.badge, 'EXPIRED');
  assert.equal(yesterday.warning, true);
});

test('an explicit end date takes precedence over offer age', () => {
  const status = getOfferStatus({ offer_valid_until: '2026-12-31', offer_date: '2020-01-01T00:00:00Z' }, now);
  assert.equal(status.muted, false);
  assert.equal(status.warning, false);
});

test('undated validity shows age in red and turns gray exactly at six months', () => {
  const recent = getOfferStatus({ offer_date: '2026-04-03T00:00:00Z' }, now);
  assert.equal(recent.badge, '5 MONTHS OLD');
  assert.equal(recent.warning, true);
  assert.equal(recent.muted, false);
  const old = getOfferStatus({ offer_date: '2026-04-02T00:00:00Z' }, now);
  assert.equal(old.badge, '6 MONTHS OLD');
  assert.equal(old.muted, true);
  assert.equal(old.expired, false);
});

test('calendar month boundaries work across years and shorter months', () => {
  const status = getOfferStatus({ offer_date: '2025-08-31T00:00:00Z' }, new Date('2026-02-28T12:00:00Z'));
  assert.equal(status.badge, '6 MONTHS OLD');
  assert.equal(status.muted, true);
});

test('recent and future dates never display a negative age', () => {
  for (const offer_date of ['2026-10-01T00:00:00Z', '2026-11-01T00:00:00Z']) {
    const status = getOfferStatus({ offer_date }, now);
    assert.equal(status.badge, 'LESS THAN 1 MONTH OLD');
    assert.equal(status.muted, false);
  }
  assert.equal(getOfferStatus({ offer_date: '2026-09-02T00:00:00Z' }, now).label, 'Offer is 1 month old');
});

test('missing and invalid offer dates are explicitly unknown', () => {
  for (const offer_date of [null, undefined, 'invalid']) {
    const status = getOfferStatus({ offer_date }, now);
    assert.equal(status.label, 'Offer date unknown');
    assert.equal(status.badge, null);
    assert.equal(status.warning, true);
    assert.equal(status.muted, false);
  }
});

test('estimated offer dates and calculated expiry dates remain labelled', () => {
  const status = getOfferStatus({
    offer_date: '2026-10-02T00:00:00Z', offer_valid_until: '2026-10-16',
    offer_date_source: 'sharepoint_created', offer_validity_source: 'relative_sharepoint_created',
  }, now);
  assert.match(status.label, /estimated from file creation/);
  assert.match(status.label, /calculated from relative validity/);
  assert.equal(status.warning, true);
  assert.equal(status.expired, false);
});

test('expiry changes at the Berlin calendar boundary', () => {
  const offer = { offer_valid_until: '2026-10-02' };
  assert.equal(getOfferStatus(offer, new Date('2026-10-02T21:59:59Z')).expired, false);
  assert.equal(getOfferStatus(offer, new Date('2026-10-02T22:00:00Z')).expired, true);
});

test('winter and daylight-saving transitions use Berlin midnight', () => {
  for (const [validUntil, midnight] of [
    ['2026-01-02', '2026-01-02T23:00:00Z'],
    ['2026-03-29', '2026-03-29T22:00:00Z'],
    ['2026-10-25', '2026-10-25T23:00:00Z'],
  ]) {
    const offer = { offer_valid_until: validUntil };
    const boundary = new Date(midnight);
    assert.equal(getOfferStatus(offer, new Date(boundary.getTime() - 1)).expired, false);
    assert.equal(getOfferStatus(offer, boundary).expired, true);
  }
});

test('open screens refresh on date changes and tab resume, and clean up listeners', async () => {
  const hookSource = await readFile(new URL('../src/features/matching/use-offer-date-refresh.ts', import.meta.url), 'utf8');
  const { outputText: hookCode } = ts.transpileModule(hookSource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  let instant = new Date('2026-10-02T21:59:59Z');
  let day;
  let cleanup;
  let tick;
  let cleared = false;
  const listeners = new Map();
  const events = {
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener: (name, callback) => {
      assert.equal(listeners.get(name), callback);
      listeners.delete(name);
    },
  };
  const windowMock = {
    ...events,
    setInterval: (callback, delay) => { assert.equal(delay, 60_000); tick = callback; return 1; },
    clearInterval: id => { assert.equal(id, 1); cleared = true; },
  };
  const reactMock = {
    useState: initial => { day = initial(); return [day, value => { day = value; }]; },
    useEffect: effect => { cleanup = effect(); },
  };
  const exports = {};
  const load = new Function('require', 'exports', 'window', 'document', 'Date', hookCode);
  load(name => name === 'react' ? reactMock : { berlinDay }, exports, windowMock, events,
    class extends Date { constructor() { super(instant.getTime()); } });
  exports.useOfferDateRefresh();
  assert.equal(day, '2026-10-02');
  instant = new Date('2026-10-02T22:00:00Z');
  tick();
  assert.equal(day, '2026-10-03');
  instant = new Date('2026-10-04T10:00:00Z');
  listeners.get('visibilitychange')();
  assert.equal(day, '2026-10-04');
  instant = new Date('2026-10-05T10:00:00Z');
  listeners.get('focus')();
  assert.equal(day, '2026-10-05');
  cleanup();
  assert.equal(cleared, true);
  assert.equal(listeners.size, 0);
});
