import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
});

for (const requestId of [null, 'draft-request']) {
  test(`App forwards selected worksheets for ${requestId ? 'draft' : 'new'} uploads`, async () => {
    const calls = [];
    const initial = ['ingestion', 'Local User', 'cat', null, requestId, null, null, false];
    let cursor = 0;
    const exports = {};
    const ingestion = () => null;
    const upload = async (...args) => {
      calls.push(args);
      return { requestId: 'saved-request' };
    };
    new Function('require', 'exports', outputText)(name => {
      if (name === 'react') return {
        ...React, useState: () => [initial[cursor++], () => {}],
        useRef: value => ({ current: value }), useEffect: () => {},
      };
      if (name === './api/client') return { createImport: upload };
      if (name === './api/workflow') return { uploadRequestFile: upload };
      if (name === './api/identity') return {};
      if (name === './components/IngestionScreen') return { IngestionScreen: ingestion };
      if (name.startsWith('./components/')) return {};
      return require(name);
    }, exports);
    const previousWindow = globalThis.window;
    globalThis.window = { location: { href: 'http://localhost:3000/?screen=ingestion' }, history: { pushState() {} } };
    try {
      const find = node => {
        if (!node || typeof node !== 'object') return;
        if (Array.isArray(node)) return node.map(find).find(Boolean);
        return node.type === ingestion ? node : find(node.props?.children);
      };
      const screen = find(exports.default());
      assert.ok(screen);
      const file = { name: 'two-sheets.xlsx' };
      const selected = ['Sheet1', 'Sheet2'];
      screen.props.onContinue(file, selected);
      await new Promise(done => setImmediate(done));
      assert.deepEqual(calls, [requestId ? [requestId, file, selected] : [file, selected]]);
    } finally {
      globalThis.window = previousWindow;
    }
  });
}
