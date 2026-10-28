import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
function compile(path, overrides = {}) {
  const exports = {};
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  new Function('require', 'exports', outputText)((name) => overrides[name] ?? require(name), exports);
  return exports;
}
const model = compile('../src/features/review/model.ts');
const queue = compile('../src/features/review/task-queue.ts');
const timeline = compile('../src/components/review/TaskTimeline.tsx');
const tools = compile('../src/components/review/ReviewTools.tsx', {
  '../../features/review/task-queue': queue,
  './TaskTimeline': timeline,
});
const items = [
  { id: 1, name: 'Thermometer', itemNumber: 'T1', domain: 'equipment', status: 'verified' },
  { id: 2, name: 'Amoxicillin 500mg', domain: 'medicine', status: 'needs_review' },
];

test('filters combine search, readiness, type and issue category without changing the items', () => {
  assert.deepEqual(
    model.filterItems(items, '500mg', 'needs', 'medicine', 'type', new Set([2])).map((i) => i.id),
    [2],
  );
  assert.deepEqual(
    model.filterItems(items, 'T1', 'ready', 'equipment', 'all', new Set()).map((i) => i.id),
    [1],
  );
  assert.equal(items.length, 2);
});

test('selection uses explicit IDs and preserves unrelated selection immutably', () => {
  const selected = new Set([1]);
  assert.deepEqual([...model.toggleSelection(selected, 2, true)], [1, 2]);
  assert.deepEqual([...selected], [1]);
  assert.deepEqual([...model.toggleSelection(selected, 1, false)], []);
});

test('review statuses distinguish readiness from AI and human provenance', () => {
  const item = { ...items[0], readyForMatching: true };
  assert.equal(model.reviewPresentation({ ...item, verificationSource: 'ai' }).label, 'AI checked');
  assert.equal(model.reviewPresentation({ ...item, verificationSource: 'human' }).label, 'Human verified');
  const edited = { ...item, fieldReviews: { quantity: { source: 'human' } } };
  assert.equal(model.reviewPresentation(edited).label, 'Human reviewed');
  assert.equal(model.reviewPresentation(item).label, 'Checks passed');
  assert.equal(model.reviewPresentation({ ...item, readyForMatching: false, verificationSource: 'ai' }).label, 'Needs human review');
  assert.equal(model.reviewPresentation({ ...item, readyForMatching: false }, [
    { itemId: null, itemIds: [item.id], scope: 'table', state: 'open' },
  ]).label, 'Shared check pending');
  assert.equal(model.reviewPresentation(item, [
    { itemId: null, itemIds: [item.id], scope: 'table', state: 'accepted' },
  ]).label, 'Human reviewed');
});

test('overview distinguishes items, issues, and tasks', () => {
  const html = renderToStaticMarkup(
    React.createElement(tools.ReviewOverview, {
      data: {
        items,
        reviewCounts: { active: 48, ready: 32, affected: 16, issues: 17, removed: 0 },
        tasks: [{ id: 'types', title: 'Choose product types', itemIds: [1, 2], suggestedValue: 'equipment' }],
      },
      onStart() {},
      onAll() {},
    }),
  );
  assert.match(html, /48/);
  assert.match(html, /32/);
  assert.match(html, /16/);
  assert.match(html, /Start guided review/);
});

test('mixed verification previews block application and offer an explicit eligible subset', () => {
  const html = renderToStaticMarkup(
    React.createElement(tools.OperationPreview, {
      operations: {
        pending: {
          operation: { action: 'verify', itemIds: [1, 2] },
          preview: {
            changes: [],
            eligibleItemIds: [1],
            blockers: [{ itemId: 2, message: 'Resolve the quantity' }],
          },
        },
        busy: false,
        error: null,
      },
    }),
  );
  assert.match(html, /Preview 1 eligible items only/);
  assert.match(html, /disabled=""[^>]*>Confirm changes/);
});

test('removal preview identifies affected items and describes recoverable removal', () => {
  const html = renderToStaticMarkup(
    React.createElement(tools.OperationPreview, {
      operations: {
        pending: {
          operation: { action: 'remove', itemIds: [1] },
          preview: {
            changes: [{ itemId: 1, name: 'Thermometer', fields: {} }],
            eligibleItemIds: [1],
            blockers: [],
          },
        },
        busy: false,
        error: null,
      },
    }),
  );
  assert.match(html, /Thermometer/);
  assert.match(html, /restore them from Removed items/);
});

test('skipping the entire queue stops instead of wrapping to its first task', () => {
  const tasks = [{ id: 'columns' }, { id: 'types' }];
  let progress = { current: null, deferred: [], history: tasks };
  assert.equal(queue.nextTask(tasks, progress).id, 'columns');
  progress = queue.deferTask(tasks, progress, 'columns');
  assert.equal(queue.nextTask(tasks, progress).id, 'types');
  progress = queue.deferTask(tasks, progress, 'types');
  assert.equal(queue.nextTask(tasks, progress), undefined);
  assert.equal(queue.nextTask(tasks, { ...progress, current: 'columns' }).id, 'columns');
});

test('timeline retains completed tasks while refreshing the remaining tasks', () => {
  const history = [
    { id: 'columns', title: 'Confirm source columns', itemIds: [1, 2] },
    { id: 'types', title: 'Choose product types', itemIds: [2] },
  ];
  const remaining = [history[1]];
  assert.equal(queue.taskHistory(history, remaining).length, 2);
  const html = renderToStaticMarkup(
    React.createElement(timeline.TaskTimeline, {
      history,
      tasks: remaining,
      current: 'types',
      deferred: [],
      onSelect() {},
    }),
  );
  assert.match(html, /1 of 2 tasks resolved/);
  assert.match(html, /Resolved/);
  assert.match(html, /aria-current="step"/);
  assert.match(html, /<nav[^>]*aria-label="Review timeline"/);
  assert.match(html, /Remaining tasks \(1\)/);
  assert.doesNotMatch(html, /<aside/);
});
