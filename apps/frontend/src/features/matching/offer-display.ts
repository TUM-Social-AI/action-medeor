export function formatOfferPrice(
  price: string | number | null | undefined,
  currency: string | null | undefined,
  basis: string | null | undefined,
  unitPrice?: string | number | null,
  unitPriceUnit?: string | null,
): string {
  const chosenPrice = unitPrice ?? price;
  const chosenUnit = unitPrice != null ? unitPriceUnit : basis;
  if (chosenPrice == null) return 'Price on request';
  const amount = Number(chosenPrice);
  if (!Number.isFinite(amount)) return 'Price on request';
  const formatted = amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
  return `${currency ? currency + ' ' : ''}${formatted}${chosenUnit ? ' / ' + chosenUnit : ''}`;
}

export function formatOfferValidUntil(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  });
}

export function isOfferExpired(value: string, now = new Date()): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && value < berlinDay(now);
}

export function berlinDay(value: Date): string {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(value);
  const part = (name: string) => parts.find(p => p.type === name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

type OfferDates = {
  offer_valid_until?: string | null; offer_date?: string | null;
  offer_date_source?: string | null; offer_validity_source?: string | null;
};
export type OfferStatus = {
  expired: boolean;
  muted: boolean;
  badge: string | null;
  label: string;
  warning: boolean;
};

function baseOfferStatus(offer: OfferDates, now = new Date()): OfferStatus {
  now = new Date(`${berlinDay(now)}T00:00:00Z`);
  if (offer.offer_valid_until) {
    const expired = isOfferExpired(offer.offer_valid_until, now);
    return {
      expired, muted: expired, badge: expired ? 'EXPIRED' : null,
      label: `${expired ? 'Expired' : 'Valid until'} ${formatOfferValidUntil(offer.offer_valid_until)}`,
      warning: expired,
    };
  }
  let date = offer.offer_date ? new Date(offer.offer_date) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return { expired: false, muted: false, badge: null, label: 'Offer date unknown', warning: true };
  }
  date = new Date(`${berlinDay(date)}T00:00:00Z`);
  // Count complete calendar months, clamping anniversaries at the end of a month.
  let months = (now.getUTCFullYear() - date.getUTCFullYear()) * 12 + now.getUTCMonth() - date.getUTCMonth();
  const lastDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate();
  if (now.getUTCDate() < Math.min(date.getUTCDate(), lastDay)) months -= 1;
  months = Math.max(0, months);
  const age = months === 0 ? 'Less than 1 month old' : `${months} month${months === 1 ? '' : 's'} old`;
  return { expired: false, muted: months >= 6, badge: age.toUpperCase(), label: `Offer is ${age.toLowerCase()}`, warning: true };
}

export function getOfferStatus(offer: OfferDates, now = new Date()): OfferStatus {
  const status = baseOfferStatus(offer, now);
  const estimates = [];
  if (offer.offer_date_source === 'sharepoint_created') estimates.push('offer date estimated from file creation');
  if (offer.offer_validity_source?.startsWith('relative_')) estimates.push('expiry calculated from relative validity');
  return estimates.length ? {
    ...status, label: `${status.label} (${estimates.join('; ')})`, warning: true,
  } : status;
}
