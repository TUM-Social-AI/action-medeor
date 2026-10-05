import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/features/matching/pack-size-display.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { getCandidatePackSize } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

test('pack contents remain visible independently of request conversion', () => {
  const candidate = {
    package: { units_per_package: '24', unit: 'roll', stock_unit: 'PAKET' },
    packaging: { status: 'unit_mismatch', basis: null },
  };
  assert.equal(getCandidatePackSize(candidate), '24 rolls / PAKET');
  assert.equal(getCandidatePackSize({ ...candidate, packaging: { status: 'unknown' } }), '24 rolls / PAKET');
  assert.equal(getCandidatePackSize({
    ...candidate, package: { units_per_package: 1, unit: 'bottle' },
  }), '1 bottle / pack');
});

test('saved package labels remain usable without source annotations on cards', () => {
  assert.equal(getCandidatePackSize({
    packaging: { basis: '24 rolls per PAKET (ERP description)' },
  }), '24 rolls per PAKET');
});

test('unknown or invalid package data never fabricates a pack size', () => {
  for (const units_per_package of [null, undefined, '', ' ', 'bad', 'Infinity', 0, -1]) {
    assert.equal(getCandidatePackSize({
      package: { units_per_package, unit: 'piece' }, packaging: { status: 'unknown' },
    }), null);
  }
  assert.equal(getCandidatePackSize({
    package: { units_per_package: 24 }, packaging: { status: 'not_required' },
  }), null);
  assert.equal(getCandidatePackSize({ packaging: { basis: ' ' } }), null);
});
