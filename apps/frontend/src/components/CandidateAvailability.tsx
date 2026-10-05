import { getCandidateAvailability, type AvailabilityCandidate } from '../features/matching/availability-display';

export function CandidateAvailability({ candidate }: { candidate: AvailabilityCandidate }) {
  const { quantity, coverage, tone } = getCandidateAvailability(candidate);
  const color = { green: 'text-green-700', red: 'text-red-700', orange: 'text-orange-700', neutral: 'text-gray-500' }[tone];
  const label = quantity ?? 'Quantity unavailable';
  return <span className={`font-medium ${color}`} title={coverage} aria-label={`${label}. ${coverage}`}>
    {label}
  </span>;
}
