/** Display a relative 0–100 score without rounding a near-top option up to 100. */
export function formatRankingScore(score: number | null | undefined): string {
  if (typeof score !== 'number' || !Number.isFinite(score)) return '—';
  if (score < 100 && score > 99.995) {
    return score.toFixed(10).replace(/0+$/, '').replace(/\.$/, '');
  }
  return score.toFixed(2).replace(/\.00$/, '');
}
