/**
 * Loading-screen progress driven by real work (issue #24), not a fixed animation.
 *
 * Extraction: the backend reports its stage (reading -> reviewing -> saving). Each stage owns a
 * span of the bar; inside the current stage the bar creeps toward the end of that span but never
 * reaches it, so it keeps moving without claiming a stage is done before the backend says so.
 *
 * Matching: progress is the real share of items the background worker has processed.
 */

export type ExtractionStage = 'uploading' | 'reading' | 'reviewing' | 'saving';
export type ExtractionMode = 'basic' | 'balanced';

const LABELS: Record<ExtractionStage, string> = {
  uploading: 'Uploading the file',
  reading: 'Reading the document and mapping its columns',
  reviewing: 'Checking items with AI',
  saving: 'Saving items',
};

// Bar spans per stage, sized by measured typical durations: the AI review is the long part.
const SPANS: Record<ExtractionMode, Partial<Record<ExtractionStage, [number, number]>>> = {
  balanced: { uploading: [0, 8], reading: [8, 45], reviewing: [45, 92], saving: [92, 100] },
  basic: { uploading: [0, 10], reading: [10, 85], saving: [85, 100] },
};

// How quickly the bar approaches the end of a stage's span (time constant, ms).
const PACE_MS: Record<ExtractionStage, number> = {
  uploading: 1500,
  reading: 6000,
  reviewing: 15000,
  saving: 1500,
};

export function extractionStages(mode: ExtractionMode): ExtractionStage[] {
  return Object.keys(SPANS[mode]) as ExtractionStage[];
}

export function extractionSteps(mode: ExtractionMode): string[] {
  return extractionStages(mode).map(stage => LABELS[stage]);
}

/** 0-100; at most 90% of the way through the current stage's span, however long it takes. */
export function extractionPercent(
  stage: ExtractionStage, mode: ExtractionMode, msInStage: number,
): number {
  const span = SPANS[mode][stage] ?? SPANS[mode].reading!;
  const [start, end] = span;
  const eased = 0.9 * (1 - Math.exp(-Math.max(0, msInStage) / PACE_MS[stage]));
  return start + (end - start) * eased;
}

// Matching: open the results once this share of items is processed (the matching screen keeps
// updating the rest), or after a cap so a slow catalogue never traps the user here.
export const MATCHING_READY_SHARE = 0.5;
export const MATCHING_MAX_WAIT_MS = 60_000;

type MatchingLine = { status: 'pending' | 'running' | 'completed' | 'failed' };
// lines/total can be absent on the fixture demo request, which answers in another shape.
type MatchingState = { status?: string; total?: number; lines?: MatchingLine[] };

export function matchingProcessed(state: MatchingState): number {
  return (state.lines ?? []).filter(line => line.status === 'completed' || line.status === 'failed').length;
}

export function matchingReady(state: MatchingState, elapsedMs: number): boolean {
  if (!state.total || !['matching_queued', 'matching'].includes(state.status ?? '')) return true;
  const processed = matchingProcessed(state);
  return (
    processed >= state.total
    || processed / state.total >= MATCHING_READY_SHARE
    || elapsedMs >= MATCHING_MAX_WAIT_MS
  );
}
