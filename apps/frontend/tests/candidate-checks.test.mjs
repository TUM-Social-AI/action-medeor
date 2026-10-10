import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
async function load(path, dependencies = {}) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  new Function('require', 'exports', outputText)(name => dependencies[name] ?? require(name), exports);
  return exports;
}
const { CandidateChecks } = await load('../src/components/CandidateChecks.tsx');

test('details show check results once and retain unrelated warnings', () => {
  const fallback = 'Ingredient not confirmed—fallback suggestion. Manual review required.';
  const html = renderToStaticMarkup(React.createElement(CandidateChecks, { candidate: {
    constraints: [
      { code: 'medicine_ingredient_fallback', outcome: 'review', message: fallback },
      { code: 'domain_match', outcome: 'pass', message: 'Candidate belongs to the requested product domain.' },
      { code: 'medicine_active_ingredient_unverified', attribute: 'active_ingredient', outcome: 'review', message: 'Ingredient could not be confirmed.' },
      { code: 'attribute_strength_mismatch', attribute: 'strength', outcome: 'review', message: 'Strength differs.' },
    ],
    warnings: [fallback, 'Strength differs.', 'Stock unknown', 'Stock unknown'],
  }}));
  assert.ok(html.includes('Product domain: Confirmed'));
  assert.ok(html.includes('Active ingredient: Not confirmed'));
  assert.ok(html.includes('Strength: Failed'));
  assert.ok(!html.includes('fallback suggestion'));
  assert.ok(!html.includes('Strength differs.'));
  assert.equal(html.match(/Stock unknown/g).length, 1);
});
