import type { CatalogueArticle } from '../../api/catalogue';

export type SourceFilter = 'all' | 'erp' | 'sharepoint';
export type Status = 'in-stock' | 'out-of-stock' | 'valid' | 'expired' | 'unknown';
export type StatusFilter = 'all' | Status;
export type CatalogueFilters = {
  query: string;
  source: SourceFilter;
  category: string;
  status: StatusFilter;
};

export const DEFAULT_FILTERS: CatalogueFilters = {
  query: '', source: 'all', category: 'all', status: 'all',
};

export const STATUSES: Status[] = ['in-stock', 'out-of-stock', 'valid', 'expired', 'unknown'];

export const categoryLabel = (category: string) =>
  category === 'medicine' ? 'Medicine' : category === 'equipment' ? 'Equipment' : 'Other';

export function statusOf(article: CatalogueArticle, today: string): Status {
  if (article.source === 'erp') {
    if (article.stock === null || !article.stock.trim() || !Number.isFinite(Number(article.stock))) return 'unknown';
    return Number(article.stock) > 0 ? 'in-stock' : 'out-of-stock';
  }
  const date = article.valid_until;
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return 'unknown';
  const parsed = new Date(`${date}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) return 'unknown';
  return date < today ? 'expired' : 'valid';
}

export function availableStatuses(source: SourceFilter): Status[] {
  if (source === 'erp') return ['in-stock', 'out-of-stock', 'unknown'];
  if (source === 'sharepoint') return ['valid', 'expired', 'unknown'];
  return STATUSES;
}

/** Status belongs to the selected source; switching source starts with all its statuses. */
export function changeSource(filters: CatalogueFilters, source: SourceFilter): CatalogueFilters {
  return source === filters.source ? filters : { ...filters, source, status: 'all' };
}

export function selectStatus(filters: CatalogueFilters, status: StatusFilter): CatalogueFilters {
  if (status !== 'all' && !availableStatuses(filters.source).includes(status)) return filters;
  return { ...filters, status: filters.status === status ? 'all' : status };
}

/** Each facet counts the results of choosing that option, before applying its own selection.
 * Source counts also omit status because switching source resets status. Search always applies.
 */
export function getCatalogueView(
  articles: CatalogueArticle[], filters: CatalogueFilters, today: string,
) {
  const term = filters.query.trim().toLocaleLowerCase();
  const sourceCounts: Record<SourceFilter, number> = { all: 0, erp: 0, sharepoint: 0 };
  const statusCounts: Record<StatusFilter, number> = {
    all: 0, 'in-stock': 0, 'out-of-stock': 0, valid: 0, expired: 0, unknown: 0,
  };
  const categoryCounts: Record<string, number> = { all: 0 };
  const rows: CatalogueArticle[] = [];
  const visibleSourceCounts = { erp: 0, sharepoint: 0 };
  const categories = [...new Set(articles.map(article => categoryLabel(article.category)))].sort();
  for (const category of categories) categoryCounts[category] = 0;

  for (const article of articles) {
    const category = categoryLabel(article.category);
    if (term && ![article.name, article.vendor, article.reference, article.category, category]
      .some(value => value?.toLocaleLowerCase().includes(term))) continue;

    const status = statusOf(article, today);
    const matchesSource = filters.source === 'all' || article.source === filters.source;
    const matchesCategory = filters.category === 'all' || category === filters.category;
    const matchesStatus = filters.status === 'all' || filters.status === status;

    if (matchesCategory) {
      sourceCounts.all += 1;
      sourceCounts[article.source] += 1;
    }
    if (matchesSource && matchesCategory) {
      statusCounts.all += 1;
      statusCounts[status] += 1;
    }
    if (matchesSource && matchesStatus) {
      categoryCounts.all += 1;
      categoryCounts[category] += 1;
    }
    if (matchesSource && matchesCategory && matchesStatus) {
      rows.push(article);
      visibleSourceCounts[article.source] += 1;
    }
  }
  return { rows, sourceCounts, statusCounts, categoryCounts, categories, visibleSourceCounts };
}
