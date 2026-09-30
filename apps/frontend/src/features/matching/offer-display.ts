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

export function isOfferExpired(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && value < new Date().toISOString().slice(0, 10);
}
