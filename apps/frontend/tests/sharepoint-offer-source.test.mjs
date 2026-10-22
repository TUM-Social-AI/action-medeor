import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = await readFile(new URL('../src/components/SharePointOfferSource.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  },
});
const exports = {};
new Function('require', 'exports', outputText)(require, exports);
const { SharePointOfferSource, sharePointDocuments } = exports;
const document = {
  source_type: 'sharepoint', document_id: 'file-1',
  uri: 'https://medeor.sharepoint.com/:x:/r/sites/offers/_layouts/15/Doc.aspx?sourcedoc=file-1',
  locator: { file_name: 'Supplier quotation October.xlsx' },
};

test('matching cards and order summaries use the catalogue filename for SharePoint viewer links', () => {
  for (const variant of ['footer', 'compact']) {
    const html = renderToStaticMarkup(React.createElement(SharePointOfferSource, {
      provenance: [document], candidateType: 'historical_offer', variant,
    }));
    assert.ok(html.includes('>Supplier quotation October.xlsx</span>'));
    assert.ok(html.includes(`href="${document.uri}"`));
    assert.ok(html.includes('title="Open Supplier quotation October.xlsx in SharePoint"'));
    assert.ok(!html.includes('>Doc.aspx</span>'));
  }
});

test('legacy sources retain decoded URL filenames when a stored name is missing or blank', () => {
  for (const file_name of [undefined, null, '', '   ', 123]) {
    const [result] = sharePointDocuments([{
      ...document, uri: 'https://medeor.sharepoint.com/offers/Supplier%20offer.xlsx',
      locator: { file_name },
    }]);
    assert.equal(result.name, 'Supplier offer.xlsx');
  }
});

test('stored filenames do not bypass SharePoint URL validation', () => {
  for (const uri of ['javascript:alert(1)', 'https://medeor.sharepoint.com.example.com/file.xlsx']) {
    assert.deepEqual(sharePointDocuments([{ ...document, uri }]), []);
  }
});
