import type { MatchCandidateV1 } from '../../api/matching/contracts';

export type AvailabilityCandidate = Pick<MatchCandidateV1,
  'available_quantity' | 'required_stock_quantity' | 'stock_unit' | 'availability_status'>;

function quantityNumber(value: string | number | null | undefined): number | null {
  return value != null && String(value).trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0
    ? Number(value) : null;
}

export function getCandidateAvailability(candidate: AvailabilityCandidate) {
  const value = candidate.available_quantity;
  const available = quantityNumber(value);
  const required = quantityNumber(candidate.required_stock_quantity);
  const unit = candidate.stock_unit?.trim();
  const quantity = available != null
    ? `${available.toLocaleString()}${unit ? ` ${unit}` : ' (unit unknown)'}`
    : null;
  let coverage = {
    on_hand_sufficient: 'Covers requested quantity',
    on_hand_partial: 'Partially covers requested quantity',
    procurement_indicated: 'Additional stock needed',
    unknown: 'Request quantity not comparable',
    not_allowed: 'Excluded from matching',
  }[candidate.availability_status];
  let tone: 'green' | 'red' | 'orange' | 'neutral' = 'neutral';
  if (available != null && unit) {
    if (candidate.availability_status === 'on_hand_sufficient') {
      tone = required != null && required > 0 && available <= required * 1.1 ? 'orange' : 'green';
      if (tone === 'orange') coverage = 'Covers requested quantity with at most 10% extra stock';
    } else if (['on_hand_partial', 'procurement_indicated', 'not_allowed'].includes(candidate.availability_status)) {
      tone = 'red';
    }
  }
  return { quantity, coverage, tone };
}
