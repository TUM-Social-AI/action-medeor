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
const guidedValues = compile('../src/features/review/guided-values.ts');
const tools = compile('../src/components/review/ReviewTools.tsx', {
  '../../features/review/task-queue': queue,
  '../../features/review/guided-values': guidedValues,
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
  ]).label, 'Checks passed');
  const mapped = { ...item, fieldReviews: { quantity: { source: 'column_mapping' } } };
  assert.equal(model.reviewPresentation(mapped).label, 'Checks passed');
  assert.equal(model.reviewPresentation(mapped, [
    { itemId: null, itemIds: [item.id], scope: 'table', state: 'accepted' },
  ]).label, 'Checks passed');
  assert.equal(model.reviewPresentation(mapped, [
    { itemId: item.id, state: 'accepted' },
  ]).label, 'Human reviewed');
  assert.equal(model.reviewPresentation(edited, [
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
  assert.match(html, /disabled=""[^>]*>Verify items/);
});

for (const [action, itemIds, tableDecision, label] of [
  ['edit', [1], null, 'Save changes'],
  ['quantity_rule', [1, 2], null, 'Update quantities'],
  ['verify', [1], null, 'Verify item'],
  ['verify', [1, 2], null, 'Verify items'],
  ['accept', [1], null, 'Keep values'],
  ['accept', [], { affectedItems: 2, columns: [] }, 'Confirm column mapping'],
  ['remove', [1], null, 'Remove item'],
  ['remove', [1, 2], null, 'Remove items'],
  ['restore', [1], null, 'Restore item'],
  ['restore', [1, 2], null, 'Restore items'],
  ['column_mapping', [1, 2], { affectedItems: 2, columns: [] }, 'Apply column mapping'],
]) {
  test(`${action} confirmation says ${label} and applies the pending operation`, async () => {
    let applied = 0;
    const tree = tools.OperationPreview({ operations: {
      pending: { operation: { action, itemIds }, preview: {
        changes: [], eligibleItemIds: itemIds, blockers: [], tableDecision,
      } }, busy: false, apply: async () => { applied++; },
    } });
    const button = buttonWithText(tree, label);
    assert.ok(button);
    assert.equal(button.props.disabled, false);
    await button.props.onClick();
    assert.equal(applied, 1);
  });
}

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
function guidedHarness(componentName = 'GuidedReview') {
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
    '../../features/review/guided-values': guidedValues,
  })[componentName];
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

const unitData = {
  requestId: 'guided-test', sourceReferences: [],
  items: [{ id: 1, name: 'Clotrimazole cream', quantity: 15000, unit: 'units', domain: 'medicine' }],
  tasks: [{ id: 'units', category: 'unit', code: 'unit_unclear', title: 'Check requested units',
    itemIds: [1], issueIds: ['unit-1'], suggestedValue: null, canAccept: true }],
  issues: [{ id: 'unit-1', itemId: 1, code: 'unit_unclear', category: 'unit', fields: ['unit'],
    message: 'The counted packaging unit is unclear.', canAccept: true, state: 'open' }],
};

test('guided unit review names the field, makes uncertainty visible and keeps one stable action', async () => {
  const screen = guidedHarness();
  try {
    const accepted = [];
    const operations = { busy: false, accept: async input => accepted.push(input) };
    let tree = screen.render(unitData, { operations });
    const html = renderToStaticMarkup(tree);
    assert.match(html, /Extracted unit/);
    assert.match(html, /Unit: /);
    assert.match(html, /Expected unit/);
    assert.match(html, /Not established/);
    assert.match(html, /Confirm what one “units” counts/);
    assert.doesNotMatch(html, /Current value|I reviewed|after inspection|Inspect each/);
    const keep = findElement(tree, e => e.type === 'button' && e.props.children === 'Keep unit');
    assert.equal(keep.props.disabled, false);
    await keep.props.onClick();
    assert.deepEqual(accepted, [{ itemIds: [1], issueIds: ['unit-1'] }]);
    tree = screen.render(unitData, { operations: { ...operations, busy: true } });
    const saving = findElement(tree, e => e.type === 'button' && e.props.children === 'Keep unit');
    assert.equal(saving.props.disabled, true);
    const noSelection = findElement(tree, e => e.props?.label === 'Select all task items');
    noSelection.props.onChange(false);
    tree = screen.render(unitData, { operations });
    assert.equal(findElement(tree, e => e.type === 'button' && e.props.children === 'Keep unit').props.disabled, true);
  } finally { screen.restore(); }
});

test('generic uncertainty labels every value and makes the absence of an alternative explicit', () => {
  const task = { ...unitData.tasks[0], category: 'other', code: 'low_confidence' };
  assert.equal(guidedValues.guidedColumnLabel(task), 'Extracted details');
  assert.deepEqual(guidedValues.guidedValues(task, unitData.items[0]), [
    { field: 'quantity', label: 'Quantity', value: '15,000' },
    { field: 'unit', label: 'Unit', value: 'units' },
    { field: 'domain', label: 'Product type', value: 'medicine' },
  ]);
  assert.match(guidedValues.guidedExpectation(task, unitData.items[0], { code: 'low_confidence' }).value,
    /Compare this row/);
  assert.deepEqual(guidedValues.guidedExpectation(unitData.tasks[0], unitData.items[0], {
    sourceValues: { unit: 'tubes' },
  }), { label: 'Source unit', value: 'tubes' });
});

test('acceptance preview identifies the field and the exact value being kept', () => {
  const html = renderToStaticMarkup(React.createElement(tools.OperationPreview, { operations: {
    pending: { operation: { action: 'accept', itemIds: [1] }, preview: {
      changes: [{ itemId: 1, name: 'Clotrimazole cream', fields: {}, keptValues: { unit: 'units' } }],
      blockers: [], eligibleItemIds: [1],
    } }, busy: false,
  } }));
  assert.match(html, /Keep Unit:/);
  assert.match(html, />units</);
});

test('type conflicts offer keep/source actions without a hidden type picker', () => {
  const screen = guidedHarness(), calls = [];
  const data = structuredClone(unitData);
  data.tasks[0].category = 'type'; data.tasks[0].code = 'type_conflict';
  data.issues[0] = { ...data.issues[0], category: 'type', code: 'type_conflict', fields: ['domain'], sourceType: 'equipment', sourceValues: { domain: 'Equipment' } };
  try {
    const tree = screen.render(data, { operations: { preview: operation => calls.push(operation) } });
    assert.ok(buttonWithText(tree, 'Keep type'));
    assert.doesNotMatch(renderToStaticMarkup(tree), /Choose type|Change product type for selected/);
    buttonWithText(tree, 'Change to source type').props.onClick();
    assert.deepEqual(calls, [{ action: 'edit', itemIds: [1], itemChanges: { 1: { domain: 'equipment' } } }]);
  } finally { screen.restore(); }
});

test('description checks are individual and names open the editor with field context', () => {
  const screen = guidedHarness(), edited = [], calls = [];
  const data = structuredClone(unitData);
  data.tasks[0].category = 'description'; data.tasks[0].code = 'name_unclear';
  data.issues[0] = { ...data.issues[0], category: 'description', code: 'name_unclear', fields: ['name'], sourceValues: { name: 'Complete source description' } };
  try {
    const tree = screen.render(data, { onEdit: (...args) => edited.push(args), operations: { preview: operation => calls.push(operation) } });
    const html = renderToStaticMarkup(tree);
    assert.doesNotMatch(html, /type="checkbox"/);
    buttonWithText(tree, 'Clotrimazole cream').props.onClick();
    assert.deepEqual(edited, [[data.items[0], ['name']]]);
    buttonWithText(tree, 'Use source description').props.onClick();
    assert.deepEqual(calls, [{ action: 'edit', itemIds: [1], changes: { name: 'Complete source description' } }]);
  } finally { screen.restore(); }
});

test('missing items are added individually and completed entries show their filled values', () => {
  const screen = guidedHarness('MissingItemsReview'), calls = [];
  const first = { ...unitData.issues[0], id: 'missing-1', code: 'coverage_uncertain', message: 'Missing blanket, 7 pcs' };
  const second = { ...first, id: 'missing-2', message: 'Missing gauze, 20 pcs' };
  const props = { issues: [first, second], items: [], operations: { busy: false }, onAdd: (...args) => calls.push(args) };
  try {
    let tree = screen.render(undefined, props);
    const addButtons = [];
    function collect(element) {
      if (!element || typeof element !== 'object') return;
      if (Array.isArray(element)) { element.forEach(collect); return; }
      if (element.type === 'button' && element.props.children === 'Add this item') addButtons.push(element);
      collect(element.props?.children);
    }
    collect(tree);
    assert.equal(addButtons.length, 2);
    addButtons[1].props.onClick();
    assert.deepEqual(calls, [['missing-2', 'Missing gauze, 20 pcs']]);
    tree = screen.render(undefined, { ...props, issues: [{ ...first, state: 'accepted', addedItemId: 7 }, second],
      items: [{ id: 7, name: 'Emergency blanket', quantity: 7, unit: 'pcs', domain: 'equipment', manual: true }] });
    const html = renderToStaticMarkup(tree);
    assert.match(html, /Emergency blanket/);
    assert.match(html, /Item 1 · Added/);
    assert.doesNotMatch(html, /Missing blanket, 7 pcs/);
    assert.match(html, /Missing gauze, 20 pcs/);
    assert.doesNotMatch(html, /No rows are missing/);
  } finally { screen.restore(); }
});

test('source-column review names its table scope and exposes mapping edits with a change preview', () => {
  const screen = guidedHarness('SourceColumnReview'), calls = [];
  const issue = { id: 'mapping', itemIds: [1, 2], worksheet: 'Column check', columns: [
    { key: '0', index: 1, label: 'Product', role: 'name' },
    { key: '1', index: 2, label: 'Amount', role: 'quantity' },
    { key: '2', index: 3, label: 'Other amount', role: 'attribute' },
  ], sampleRows: [] };
  const props = { issue, total: 22, operations: { busy: false, preview: operation => calls.push(operation) } };
  try {
    let tree = screen.render(undefined, props);
    assert.match(renderToStaticMarkup(tree), /Column check/);
    assert.match(renderToStaticMarkup(tree), /2 affected items out of 22/);
    assert.equal(buttonWithText(tree, 'Change column mapping').props.disabled, true);
    findElement(tree, e => e.props?.['aria-label'] === 'Map Amount').props.onChange({ target: { value: 'attribute' } });
    tree = screen.render(undefined, props);
    findElement(tree, e => e.props?.['aria-label'] === 'Map Other amount').props.onChange({ target: { value: 'quantity' } });
    tree = screen.render(undefined, props);
    assert.equal(buttonWithText(tree, 'Keep existing mapping').props.disabled, false);
    buttonWithText(tree, 'Change column mapping').props.onClick();
    assert.deepEqual(calls, [{ action: 'column_mapping', itemIds: [1, 2], issueIds: ['mapping'], columnRoles: { 0: 'name', 1: 'attribute', 2: 'quantity' } }]);
  } finally { screen.restore(); }
});

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
    const skip = findElement(tree, element => element.type === 'button' && renderToStaticMarkup(element).includes('Skip'));
    skip.props.onClick();
    tree = screen.render(guidedData);
    assert.equal(screen.current(tree), null);
    assert.match(renderToStaticMarkup(tree), /End of review sequence/);
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

test('finishing a middle timeline task advances forward even when earlier tasks are open', () => {
  const screen = guidedHarness();
  const later = { ...quantityTask, id: 'later', title: 'Later task', issueIds: ['later-1'], itemIds: [3] };
  const data = { ...guidedData, tasks: [typeTask, quantityTask, later] };
  try {
    let tree = screen.render(data);
    tree.props.children[0].props.onSelect(quantityTask.id);
    tree = screen.render(data);
    assert.equal(screen.current(tree), quantityTask.id);
    tree = screen.render({ ...data, tasks: [typeTask, later] });
    assert.equal(screen.current(tree), later.id);
    tree = screen.render({ ...data, tasks: [typeTask] });
    assert.equal(screen.current(tree), null);
    assert.match(renderToStaticMarkup(tree), /End of review sequence/);
    assert.equal(queue.nextTask([typeTask], { current: later.id, deferred: [], history: data.tasks }), undefined);
  } finally { screen.restore(); }
});

test('unit review offers the approved Stück default without altering quantity', () => {
  const screen = guidedHarness(), calls = [];
  try {
    const tree = screen.render(unitData, { operations: { preview: operation => calls.push(operation) } });
    buttonWithText(tree, 'Use Stück (default)').props.onClick();
    assert.deepEqual(calls, [{ action: 'edit', itemIds: [1], changes: { unit: 'Stück' } }]);
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

const buttonWithText = (tree, label) => findElement(tree, element => element.type === 'button' && renderToStaticMarkup(element).replace(/<[^>]*>/g, '').trim() === label);

test('copied quantities offer adjacent keep/change choices with an editable quantity', () => {
  const screen = guidedHarness(), calls = [];
  try {
    let tree = screen.render(quantityData([{}]), { operations: { preview: operation => calls.push(operation) } });
    const html = renderToStaticMarkup(tree);
    assert.match(html, /Source quantity/);
    assert.match(html, />12</);
    assert.doesNotMatch(html, /×|pack calculation/);
    const keep = buttonWithText(tree, 'Keep extracted value');
    const change = buttonWithText(tree, 'Change quantity');
    assert.match(keep.props.className, /teal/);
    assert.match(change.props.className, /1B4E8A/);
    change.props.onClick();
    assert.deepEqual(calls, [{ action: 'quantity_rule', itemIds: [1], rule: 'requested_total' }]);
    const input = findElement(tree, e => e.type === 'input' && e.props.type === 'number');
    assert.ok(input);
    input.props.onChange({ target: { value: '17' } });
    tree = screen.render(quantityData([{}]), { operations: { preview: operation => calls.push(operation) } });
    buttonWithText(tree, 'Change quantity').props.onClick();
    assert.deepEqual(calls[1], { action: 'quantity_rule', itemIds: [1], rule: 'explicit', changes: { quantity: 17 } });
  } finally { screen.restore(); }
});

test('pack conflicts show extracted quantity separately from the red calculation and use per-row totals', () => {
  const screen = guidedHarness(), calls = [];
  const data = quantityData([{ requestedTotal: 800, packs: 10, unitsPerPack: 100, calculatedTotal: 1000 }]);
  data.tasks[0].code = 'pack_total_conflict'; data.issues[0].code = 'pack_total_conflict'; data.items[0].quantity = 800;
  try {
    let tree = screen.render(data, { operations: { preview: operation => calls.push(operation) } });
    const html = renderToStaticMarkup(tree);
    assert.match(html, /10 × 100 = 1,000 ≠ 800/);
    assert.match(html, /text-red-700/);
    assert.ok(buttonWithText(tree, 'Keep extracted value'));
    const update = findElement(tree, e => e.type === 'button' && renderToStaticMarkup(e).includes('Update to 1,000'));
    update.props.onClick();
    assert.deepEqual(calls, [{ action: 'quantity_rule', itemIds: [1], rule: 'pack_calculation' }]);
    const missing = structuredClone(data); missing.issues[0].calculatedTotal = null;
    tree = screen.render(missing);
    const disabled = findElement(tree, e => e.type === 'button' && renderToStaticMarkup(e).includes('Update to '));
    assert.equal(disabled.props.disabled, true);
    assert.doesNotMatch(renderToStaticMarkup(tree), /×/);
  } finally { screen.restore(); }
});

test('source quantity changes preserve different source values across selected rows', () => {
  const screen = guidedHarness(), calls = [];
  try {
    const tree = screen.render(quantityData([{ requestedTotal: 12 }, { requestedTotal: 24 }]),
      { operations: { preview: operation => calls.push(operation) } });
    buttonWithText(tree, 'Change quantity').props.onClick();
    assert.deepEqual(calls, [{ action: 'quantity_rule', itemIds: [1, 2], rule: 'requested_total' }]);
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
