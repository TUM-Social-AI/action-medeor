import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/features/loading/progress.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const progress = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

test('extraction never claims a stage is done before the backend reports the next one', () => {
  // However long the AI review takes, the bar stays inside the review span (45-92)...
  const longReview = progress.extractionPercent('reviewing', 'balanced', 10 * 60_000);
  assert.ok(longReview > 85 && longReview < 92);
  // ...and keeps moving while it waits, so it never looks frozen.
  assert.ok(progress.extractionPercent('reviewing', 'balanced', 20_000)
    > progress.extractionPercent('reviewing', 'balanced', 5_000));
  // A reported stage always starts at or beyond everything before it.
  assert.ok(progress.extractionPercent('saving', 'balanced', 0) >= longReview);
});

test('basic mode has no AI review step', () => {
  assert.deepEqual(progress.extractionStages('basic'), ['uploading', 'reading', 'saving']);
  assert.ok(progress.extractionSteps('balanced').includes('Checking items with AI'));
});

test('matching opens once enough items are processed, or after the cap', () => {
  const lines = (done, total) => Array.from({ length: total }, (_, i) => ({ status: i < done ? 'completed' : 'pending' }));
  const state = (done, total, status = 'matching') => ({ status, total, lines: lines(done, total) });
  assert.equal(progress.matchingReady(state(10, 85), 1000), false);
  assert.equal(progress.matchingReady(state(43, 85), 1000), true); // >= 50%
  assert.equal(progress.matchingReady(state(1, 85), progress.MATCHING_MAX_WAIT_MS), true);
  assert.equal(progress.matchingReady(state(2, 85, 'matching_failed'), 0), true); // don't wait on a failure
  assert.equal(progress.matchingProcessed({ lines: [{ status: 'failed' }, { status: 'running' }] }), 1);
  assert.equal(progress.matchingReady({}, 0), true); // fixture demo request shape
});
