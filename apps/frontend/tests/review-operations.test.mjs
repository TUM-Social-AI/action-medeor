import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }

function harness(client) {
  let cursor = 0;
  const slots = [];
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useRef(initial) { return hooks.useState(() => ({ current: initial }))[0]; },
    useEffect() {},
  };
  let data = { reviewRevision: 4, issues: [] };
  const refreshed = [];
  const exports = {};
  const source = readFileSync(new URL('../src/features/review/use-review-operations.ts', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'exports', compiled)(name => {
    if (name === 'react') return hooks;
    if (name.endsWith('/api/client')) return client;
    if (name.endsWith('/api/http')) return { ApiError };
    throw new Error(name);
  }, exports);
  return { refreshed, render() {
    cursor = 0;
    return exports.useReviewOperations('test-request', data, review => { data = review; refreshed.push(review); });
  } };
}

const selection = { itemIds: [2, 1], issueIds: ['unit-2', 'unit-1'] };

test('keeping shown values saves once without a preview and exposes undo', async () => {
  const calls = [];
  const screen = harness({
    applyReviewOperation: async (id, operation) => {
      calls.push({ id, operation });
      return { review: { reviewRevision: 5, issues: [] }, operationId: operation.operationId };
    },
    previewReviewOperation() { assert.fail('Acceptance must not open a preview'); },
  });
  assert.equal(await screen.render().accept(selection), true);
  const state = screen.render();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].operation.itemIds, [1, 2]);
  assert.deepEqual(calls[0].operation.issueIds, ['unit-1', 'unit-2']);
  assert.equal(calls[0].operation.expectedRevision, 4);
  assert.equal(calls[0].operation.action, 'accept');
  assert.equal(state.pending, null);
  assert.equal(state.lastUndoId, calls[0].operation.operationId);
  assert.equal(screen.refreshed.length, 1);
});

test('a failed save keeps the action retryable with the same operation identity', async () => {
  const calls = [];
  const screen = harness({ applyReviewOperation: async (_id, operation) => {
    calls.push(operation);
    if (calls.length === 1) throw new Error('Connection interrupted');
    return { review: { reviewRevision: 5 }, operationId: operation.operationId };
  } });
  assert.equal(await screen.render().accept(selection), false);
  assert.equal(screen.render().error, 'Connection interrupted');
  assert.equal(await screen.render().accept(selection), true);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(screen.render().error, null);
});

test('duplicate clicks and empty issue selections do not send extra operations', async () => {
  let release;
  let calls = 0;
  const screen = harness({ applyReviewOperation: async (_id, operation) => {
    calls++;
    await new Promise(resolve => { release = resolve; });
    return { review: { reviewRevision: 5 }, operationId: operation.operationId };
  } });
  const first = screen.render().accept(selection);
  assert.equal(await screen.render().accept(selection), false);
  assert.equal(screen.render().busy, true);
  release();
  await first;
  assert.equal(await screen.render().accept({ itemIds: [1], issueIds: [] }), false);
  assert.equal(calls, 1);
});

test('stale review errors refresh the data and retry against the new revision', async () => {
  const calls = [];
  const screen = harness({
    applyReviewOperation: async (_id, operation) => {
      calls.push(operation);
      if (calls.length === 1) throw new ApiError('Review changed', 409);
      return { review: { reviewRevision: 6 }, operationId: operation.operationId };
    },
    getReview: async () => ({ reviewRevision: 5 }),
  });
  await screen.render().accept(selection);
  assert.equal(screen.render().error, 'Review changed');
  await screen.render().accept(selection);
  assert.equal(calls[1].expectedRevision, 5);
  assert.notEqual(calls[0].operationId, calls[1].operationId);
});

test('filling a missing item is one retry-safe call and exposes its undo operation', async () => {
  const calls = [];
  const item = { name: 'Blanket', quantity: 7, unit: 'pcs', domain: 'equipment' };
  const screen = harness({ resolveMissingItem: async (_id, submission) => {
    calls.push(submission);
    if (calls.length === 1) throw new Error('Connection lost');
    return { review: { reviewRevision: 5, items: [{ ...item, id: 8 }] }, operationId: submission.operationId, itemId: 8 };
  } });
  assert.equal(await screen.render().resolveMissing({ issueId: 'missing-1', item }), false);
  assert.equal(await screen.render().resolveMissing({ issueId: 'missing-1', item }), true);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(screen.render().lastUndoId, calls[1].operationId);
  assert.match(screen.render().toast.message, /Blanket/);
});
