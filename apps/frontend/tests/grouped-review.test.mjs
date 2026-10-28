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

test('request metadata is a separate guided step with no item issues', () => {
  const tasks = [{ id: 'columns', itemIds: [1, 2] }];
  const steps = queue.reviewSteps(tasks, true);
  assert.equal(steps.at(-1).id, 'request-details');
  assert.deepEqual(steps.at(-1).itemIds, []);
  assert.deepEqual(steps.at(-1).issueIds, []);
  assert.equal(queue.reviewSteps(tasks, false), tasks);
  assert.equal(tasks.length, 1);
  const progress = { current: null, deferred: ['columns'], history: steps };
  assert.equal(queue.nextTask(steps, progress).id, 'request-details');
});

// Render the actual guided component across server refreshes, with reduced motion to make
// navigation deterministic. A pure nextTask test would miss an automatically selected task
// never being saved as the current task.
function guidedHarness() {
  const slots = [];
  let cursor = 0, effects = [], dirty = false;
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => {
        const next = typeof value === 'function' ? value(slots[index]) : value;
        if (!Object.is(next, slots[index])) { slots[index] = next; dirty = true; }
      }];
    },
    useRef(initial) { return hooks.useState(() => ({ current: initial }))[0]; },
    useEffect(callback, dependencies) {
      const index = cursor++;
      const previous = slots[index];
      if (!previous || dependencies.some((value, i) => value !== previous.dependencies[i])) {
        slots[index] = { dependencies, cleanup: previous?.cleanup };
        effects.push(() => { previous?.cleanup?.(); slots[index].cleanup = callback(); });
      }
    },
  };
  const component = compile('../src/components/review/ReviewTools.tsx', {
    react: hooks, '../../features/review/task-queue': queue, './TaskTimeline': timeline,
  }).GuidedReview;
  const saved = new Map();
  const previousWindow = globalThis.window, previousStorage = globalThis.sessionStorage;
  globalThis.window = { matchMedia: () => ({ matches: true }) };
  globalThis.sessionStorage = { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  return {
    render(data, extra = {}) {
      for (let iteration = 0; iteration < 15; iteration++) {
        cursor = 0; effects = []; dirty = false;
        const tree = component({ data, hidden: false, operations: {}, onEdit() {}, onAll() {}, ...extra });
        effects.forEach(effect => effect());
        if (!dirty) return tree;
      }
      throw new Error('Guided component did not settle');
    },
    current(tree) { return tree.props.children[0].props.current; },
    savedCurrent() { return JSON.parse(saved.get('review-progress:v2:guided-test')).current; },
    restore() { globalThis.window = previousWindow; globalThis.sessionStorage = previousStorage; },
  };
}

const typeTask = {
  id: 'types', category: 'type', code: 'type_required', title: 'Choose product types',
  itemIds: [1, 3], issueIds: ['type-1', 'type-3'], suggestedValue: null, canAccept: false,
};
const quantityTask = {
  id: 'quantities', category: 'quantity', code: 'quantity_required', title: 'Complete quantities',
  itemIds: [2], issueIds: ['quantity-2'], suggestedValue: null, canAccept: false,
};
const guidedData = {
  requestId: 'guided-test', tasks: [typeTask, quantityTask], sourceReferences: [],
  items: [1, 2, 3].map(id => ({ id, name: `Supply ${id}`, quantity: id === 2 ? null : 10, unit: 'pcs' })),
  issues: [],
};

function findElement(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Array.isArray(tree)) return tree.map(child => findElement(child, predicate)).find(Boolean);
  if (predicate(tree)) return tree;
  return findElement(tree.props?.children, predicate);
}

test('an automatic guided task stays selected when an individual save reorders unfinished tasks', () => {
  const screen = guidedHarness();
  try {
    let tree = screen.render(guidedData);
    assert.equal(screen.current(tree), 'types');
    // Fixing item 1 leaves one type problem. Quantity now sorts first because its source
    // row precedes item 3, even though the current type task is not finished.
    const refreshed = { ...guidedData, tasks: [quantityTask, { ...typeTask, itemIds: [3], issueIds: ['type-3'] }] };
    tree = screen.render(refreshed);
    assert.equal(screen.current(tree), 'types');
    assert.equal(screen.savedCurrent(), 'types');
    assert.match(renderToStaticMarkup(tree), /Choose product types/);
    assert.match(renderToStaticMarkup(tree), /Supply 3/);
    assert.doesNotMatch(renderToStaticMarkup(tree), /Supply 1/);
    // Resolving the last item still advances normally, and pins the next task as well.
    tree = screen.render({ ...refreshed, tasks: [quantityTask] });
    assert.equal(screen.current(tree), 'quantities');
    assert.equal(screen.savedCurrent(), 'quantities');
  } finally { screen.restore(); }
});

test('explicit guided navigation, skipping, and request-details navigation override the active task', () => {
  const screen = guidedHarness();
  try {
    let tree = screen.render(guidedData);
    tree.props.children[0].props.onSelect('quantities');
    tree = screen.render(guidedData);
    assert.equal(screen.current(tree), 'quantities');
    const skip = findElement(tree, element => element.type === 'button' && renderToStaticMarkup(element).includes('Review later'));
    skip.props.onClick();
    tree = screen.render(guidedData);
    assert.equal(screen.current(tree), 'types');
    const details = { confirmed: false, open: true, visit: 1, content: React.createElement('p', {}, 'Request metadata') };
    tree = screen.render(guidedData, { requestDetails: details });
    assert.equal(screen.current(tree), 'request-details');
    assert.equal(screen.savedCurrent(), 'request-details');
  } finally { screen.restore(); }
});

test('opening request details on first guided entry takes priority over automatic task selection', () => {
  const screen = guidedHarness();
  try {
    const tree = screen.render(guidedData, {
      requestDetails: { confirmed: false, open: true, visit: 1, content: React.createElement('p', {}, 'Request metadata') },
    });
    assert.equal(screen.current(tree), 'request-details');
    assert.equal(screen.savedCurrent(), 'request-details');
  } finally { screen.restore(); }
});

function quantityData(facts) {
  const issues = facts.map((values, index) => ({
    id: `quantity-${index + 1}`, itemId: index + 1, code: 'quantity_conflict', category: 'totals',
    fields: ['quantity', 'unit'], state: 'open', canAccept: true,
    message: 'Copied quantity differs from the requested source total',
    requestedTotal: 12, packs: null, unitsPerPack: null, calculatedTotal: null, ...values,
  }));
  return {
    requestId: 'quantity-test', issues,
    items: issues.map(issue => ({ id: issue.itemId, name: `Copied item ${issue.itemId}`, quantity: 9, unit: 'pcs' })),
    sourceReferences: issues.map(issue => ({ itemId: issue.itemId, row: 8, excerpt: 'Requested quantity in original source' })),
    tasks: [{ id: 'copied-quantities', category: 'totals', code: 'quantity_conflict', title: 'Check copied quantities',
      itemIds: issues.map(issue => issue.itemId), issueIds: issues.map(issue => issue.id), suggestedValue: null, canAccept: true }],
  };
}

const buttonWithText = (tree, label) => findElement(tree, element => element.type === 'button' && element.props.children === label);

test('a copied-quantity mismatch offers its real source value without empty pack math or an unavailable action', () => {
  const screen = guidedHarness();
  const calls = [];
  try {
    const tree = screen.render(quantityData([{}]), { operations: { preview: operation => calls.push(operation) } });
    const html = renderToStaticMarkup(tree);
    assert.match(html, /Source quantity: 12/);
    assert.doesNotMatch(html, /×|pack calculation/);
    const useSource = buttonWithText(tree, 'Use source quantity (12)');
    assert.equal(useSource.props.disabled, false);
    useSource.props.onClick();
    assert.deepEqual(calls, [{ action: 'quantity_rule', itemIds: [1], rule: 'requested_total' }]);
    assert.match(html, /Or enter a quantity/);
  } finally { screen.restore(); }
});

test('real differing pack totals stay available while duplicate, incomplete, and invalid calculations are omitted', () => {
  const screen = guidedHarness();
  try {
    let tree = screen.render(quantityData([{ requestedTotal: 800, packs: 10, unitsPerPack: 100, calculatedTotal: 1000 }]));
    assert.match(renderToStaticMarkup(tree), /Packs: 10 × 100 = 1000/);
    assert.equal(buttonWithText(tree, 'Use source quantity (800)').props.disabled, false);
    assert.equal(buttonWithText(tree, 'Use pack calculation (1000)').props.disabled, false);
    tree = screen.render(quantityData([{ packs: 2, unitsPerPack: 6, calculatedTotal: 12 }]));
    assert.match(renderToStaticMarkup(tree), /Packs: 2 × 6 = 12/);
    assert.equal(buttonWithText(tree, 'Use pack calculation (12)'), undefined);
    for (const values of [{ packs: 0, unitsPerPack: 100, calculatedTotal: 0 }, { calculatedTotal: 1000 }]) {
      tree = screen.render(quantityData([values]));
      assert.doesNotMatch(renderToStaticMarkup(tree), /×|pack calculation/);
    }
    tree = screen.render(quantityData([{ requestedTotal: null }]));
    assert.match(renderToStaticMarkup(tree), />Enter a quantity</);
    assert.doesNotMatch(renderToStaticMarkup(tree), /Use source quantity|pack calculation/);
  } finally { screen.restore(); }
});

test('quantity-rule choices follow the selected rows and preserve per-row source rules', () => {
  const screen = guidedHarness();
  const data = quantityData([
    { packs: 2, unitsPerPack: 10, calculatedTotal: 20 },
    { requestedTotal: 24 },
  ]);
  const calls = [], operations = { preview: operation => calls.push(operation) };
  try {
    let tree = screen.render(data, { operations });
    assert.ok(buttonWithText(tree, 'Use each row’s requested total'));
    assert.equal(buttonWithText(tree, 'Use each row’s pack calculation'), undefined);
    findElement(tree, element => element.props?.label === 'Select Copied item 2').props.onChange(false);
    tree = screen.render(data, { operations });
    const usePacks = buttonWithText(tree, 'Use pack calculation (20)');
    assert.equal(usePacks.props.disabled, false);
    usePacks.props.onClick();
    assert.deepEqual(calls, [{ action: 'quantity_rule', itemIds: [1], rule: 'pack_calculation' }]);
    findElement(tree, element => element.props?.label === 'Select Copied item 2').props.onChange(true);
    tree = screen.render(data, { operations });
    assert.equal(buttonWithText(tree, 'Use each row’s pack calculation'), undefined);
  } finally { screen.restore(); }
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
