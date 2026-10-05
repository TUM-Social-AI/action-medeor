import type { MatchCandidateV1 } from '../../api/matching/contracts';

type PackageCandidate = Pick<MatchCandidateV1, 'package' | 'packaging'>;

const PLURAL_UNITS: Record<string, string> = {
  piece: 'pieces', tablet: 'tablets', capsule: 'capsules', bottle: 'bottles',
  vial: 'vials', ampoule: 'ampoules', sachet: 'sachets', suppository: 'suppositories',
  inhaler: 'inhalers', pair: 'pairs', roll: 'rolls', tube: 'tubes', test: 'tests',
  kit: 'kits', set: 'sets',
};

export function getCandidatePackSize(candidate: PackageCandidate): string | null {
  const pack = candidate.package;
  const value = pack?.units_per_package;
  const count = value != null && String(value).trim() !== '' ? Number(value) : NaN;
  const unit = pack?.unit?.trim();
  if (Number.isFinite(count) && count > 0 && unit) {
    const contents = count === 1 ? unit : PLURAL_UNITS[unit.toLowerCase()] ?? unit;
    return `${count.toLocaleString()} ${contents} / ${pack?.stock_unit?.trim() || 'pack'}`;
  }
  // Older responses may only contain the confirmed package label.
  return candidate.packaging.basis?.replace(/\s*\(ERP description\)\s*$/, '').trim() || null;
}
