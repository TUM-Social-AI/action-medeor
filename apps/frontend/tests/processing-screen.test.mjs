import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const transpile = async path => ts.transpileModule(
  await readFile(new URL(path, import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } },
).outputText;
const progress = {};
new Function('require', 'exports', await transpile('../src/features/loading/progress.ts'))(require, progress);
const screen = {};
new Function('require', 'exports', await transpile('../src/components/ProcessingScreen.tsx'))(name => {
  if (name === '../api/client') return { getImportProgress: () => new Promise(() => {}) };
  if (name === '../features/loading/progress') return progress;
  if (name === './WorkflowStepper') return { WorkflowStepper: () => null };
  return require(name);
}, screen);

const render = props => renderToStaticMarkup(React.createElement(screen.ProcessingScreen, props));

test('matching shows the real processed count and a matching progress bar', () => {
  const html = render({ type: 'matching', matching: { processed: 12, total: 48 } });
  assert.ok(html.includes('12 of 48 items matched'));
  assert.ok(html.includes('aria-valuenow="25"'));
});

test('extraction starts at the upload step with real stage labels, not a finished animation', () => {
  const html = render({ type: 'extracting', progressToken: 'token-123456' });
  assert.ok(html.includes('Uploading the file'));
  assert.ok(html.includes('Checking items with AI'));
  assert.ok(html.includes('aria-valuenow="0"'));
});
