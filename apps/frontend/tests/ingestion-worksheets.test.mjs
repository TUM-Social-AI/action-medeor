import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = await readFile(new URL('../src/components/IngestionScreen.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
});

function screen(inspectImport, deferUpdates = false) {
  const updates = [];
  const slots = [];
  let cursor = 0;
  let effects = [];
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => {
        const update = () => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; };
        if (deferUpdates && typeof value === 'function') updates.push(update); else update();
      }];
    },
    useRef(initial) {
      const index = cursor++;
      return slots[index] ??= { current: initial };
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!slots[index] || deps.some((value, i) => value !== slots[index][i])) {
        slots[index] = deps;
        effects.push(effect);
      }
    },
  };
  const exports = {};
  new Function('require', 'exports', outputText)(name => {
    if (name === 'react') return hooks;
    if (name === '../api/client') return { inspectImport };
    if (name === '../api/workflow') return { listRequests: async () => [] };
    if (name === './ScreenState' || name === './WorkflowStepper') return {};
    return require(name);
  }, exports);
  const continued = [];
  let tree;
  function nodes(element, predicate) {
    if (!element || typeof element !== 'object') return [];
    if (Array.isArray(element)) return element.flatMap(child => nodes(child, predicate));
    return [...(predicate(element) ? [element] : []), ...nodes(element.props?.children, predicate)];
  }
  return {
    continued,
    render() {
      updates.splice(0).forEach(update => update());
      cursor = 0;
      tree = exports.IngestionScreen({ onContinue: (...args) => continued.push(args), onOpenRequest() {}, onStartManual() {} });
      const pending = effects; effects = []; pending.forEach(effect => effect());
    },
    find(predicate) { return nodes(tree, predicate); },
  };
}

test('inspection precedes extraction, defaults to first sheet, and allows several sheets', async () => {
  let resolve;
  const ui = screen(() => new Promise(done => { resolve = done; }));
  ui.render();
  const file = { name: 'request.xlsx', size: 100 };
  ui.find(node => node.type === 'input' && node.props.type === 'file')[0].props.onChange({ target: { files: [file] } });
  ui.render();
  ui.render();
  const continueButton = () => ui.find(node => node.type === 'button' && node.props.children?.[0] === 'Continue to Review')[0];
  assert.equal(continueButton().props.disabled, true);
  assert.deepEqual(ui.continued, []);
  resolve({ sheets: [{ name: 'First', rows: 10 }, { name: 'Second', rows: 5 }] });
  await new Promise(done => setImmediate(done));
  ui.render();
  const boxes = () => ui.find(node => node.type === 'input' && node.props.type === 'checkbox');
  assert.deepEqual(boxes().map(box => box.props.checked), [true, false]);
  boxes()[0].props.onChange({ currentTarget: { checked: false }, target: { checked: false } });
  ui.render();
  assert.equal(continueButton().props.disabled, true);
  boxes()[0].props.onChange({ currentTarget: { checked: true }, target: { checked: true } });
  boxes()[1].props.onChange({ currentTarget: { checked: true }, target: { checked: true } });
  ui.render();
  assert.equal(continueButton().props.disabled, false);
  continueButton().props.onClick();
  assert.deepEqual(ui.continued, [[file, ['First', 'Second']]]);
});


test('worksheet selection snapshots checked state before deferred React updates', async () => {
  const ui = screen(async () => ({ sheets: [{ name: 'First', rows: 3 }, { name: 'Second', rows: 3 }] }), true);
  ui.render();
  const file = { name: 'two.xlsx', size: 100 };
  ui.find(node => node.type === 'input' && node.props.type === 'file')[0].props.onChange({ target: { files: [file] } });
  ui.render();
  await new Promise(done => setImmediate(done));
  ui.render();
  const input = { checked: true };
  ui.find(node => node.type === 'input' && node.props.type === 'checkbox')[1].props.onChange({ target: input, currentTarget: input });
  // React can restore a controlled input before evaluating its queued state updater.
  input.checked = false;
  ui.render();
  const boxes = ui.find(node => node.type === 'input' && node.props.type === 'checkbox');
  assert.deepEqual(boxes.map(box => box.props.checked), [true, true]);
  ui.find(node => node.type === 'button' && node.props.children?.[0] === 'Continue to Review')[0].props.onClick();
  assert.deepEqual(ui.continued, [[file, ['First', 'Second']]]);
});
