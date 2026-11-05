import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = await readFile(new URL('../src/components/RequestedItemName.tsx', import.meta.url), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
function screen(api, translatedName = null, originalLanguage = 'en') {
  const slots = [];
  let cursor = 0;
  const hooks = { ...React, useState(initial) {
    const index = cursor++;
    if (!(index in slots)) slots[index] = initial;
    return [slots[index], value => { slots[index] = value; }];
  }, useRef(initial) {
    const index = cursor++;
    if (!(index in slots)) slots[index] = { current: initial };
    return slots[index];
  } };
  const exports = {};
  new Function('require', 'exports', output)(name => name === 'react' ? hooks
    : name === '../api/workflow' ? { translateRequestItem: api } : require(name), exports);
  return () => {
    cursor = 0;
    const tree = exports.RequestedItemName({ requestId: 'request', line: { itemId: 1, name: 'Needle 21G', translatedName, originalLanguage } });
    const button = tree.props.children.find(child => child?.type === 'button');
    return { html: renderToStaticMarkup(tree), button };
  };
}

test('translation replaces the name, toggles back, and makes only one API call', async () => {
  let calls = 0, resolve;
  const render = screen(() => { calls++; return new Promise(done => { resolve = done; }); });
  assert.equal(render().button.props.children, 'Generate translation');
  render().button.props.onClick();
  assert.equal(render().button.props.disabled, true);
  render().button.props.onClick();
  assert.equal(calls, 1);
  resolve({ translation: 'Nadel 21G' });
  await new Promise(done => setImmediate(done));
  assert.match(render().html, /lang="de"[^>]*>Nadel 21G/);
  assert.doesNotMatch(render().html, /Needle 21G/);
  assert.equal(render().button.props.children, 'Back to original');
  render().button.props.onClick();
  assert.match(render().html, /Needle 21G/);
  assert.equal(render().button.props.children, 'See translation');
  render().button.props.onClick();
  assert.match(render().html, /Nadel 21G/);
  assert.equal(calls, 1);
});

test('saved translations are reused after reload and errors allow retry', async () => {
  const saved = screen(() => { throw new Error('must use cache'); }, 'Nadel 21G');
  saved().button.props.onClick();
  assert.match(saved().html, /Nadel 21G/);
  let calls = 0;
  const retry = screen(async () => {
    if (++calls === 1) throw new Error('offline');
    return { translation: 'Nadel 21G' };
  });
  retry().button.props.onClick();
  await new Promise(done => setImmediate(done));
  assert.match(retry().html, /role="alert"/);
  assert.match(retry().html, /Needle 21G/);
  retry().button.props.onClick();
  await new Promise(done => setImmediate(done));
  assert.match(retry().html, /Nadel 21G/);
  assert.doesNotMatch(retry().html, /role="alert"/);
});

test('translation actions work for any original language without a language switch', () => {
  for (const language of ['fr', 'ar', 'de', null]) {
    const render = screen(() => {}, 'Nadel 21G', language);
    assert.equal(render().button.props.children, 'See translation');
    assert.doesNotMatch(render().html, /role="switch"/);
    render().button.props.onClick();
    assert.equal(render().button.props.children, 'Back to original');
  }
});
