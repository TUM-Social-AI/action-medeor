import type { MatchCandidateV1 } from '../api/matching/contracts';

export function CandidateChecks({ candidate }: { candidate: MatchCandidateV1 }) {
  const checks = candidate.constraints.filter(check => check.code !== 'medicine_ingredient_fallback');
  const checkMessages = new Set(candidate.constraints.map(check => check.message));
  const warnings = [...new Set(candidate.warnings)].filter(warning => !checkMessages.has(warning));
  return <>
    {checks.length > 0 && <>
      <h3 className="text-sm font-semibold mb-2">Checks</h3>
      <ul className="space-y-1 mb-5 text-sm">{checks.map(check => {
        const label = check.attribute
          ? check.attribute.replace(/_/g, ' ').replace(/^./, value => value.toUpperCase())
          : check.code.startsWith('domain_') ? 'Product domain'
            : check.code.replace(/_/g, ' ').replace(/^./, value => value.toUpperCase());
        const status = check.outcome === 'pass' ? 'Confirmed'
          : check.outcome === 'exclude' || check.code.endsWith('_mismatch') ? 'Failed'
            : check.outcome === 'unknown' || /_(missing|unverified)$/.test(check.code) ? 'Not confirmed'
              : 'Needs review';
        return <li key={check.code} className={check.outcome === 'pass' ? 'text-gray-600' : 'text-amber-700'}>{label}: {status}</li>;
      })}</ul>
    </>}
    {warnings.length > 0 && <>
      <h3 className="text-sm font-semibold mb-2">Warnings</h3>
      <ul className="space-y-1 text-sm text-amber-700">{warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
    </>}
  </>;
}
