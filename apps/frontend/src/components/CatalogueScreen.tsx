import { useEffect, useMemo, useState } from 'react';
import {
  ArrowDown, ArrowUp, ArrowUpDown, CalendarX2, Database, ExternalLink,
  FileText, PackageSearch, RefreshCw, Search, X,
} from 'lucide-react';
import { getCatalogueArticles, type CatalogueArticle } from '../api/catalogue';

type SourceFilter = 'all' | 'erp' | 'sharepoint';
type Status = 'in-stock' | 'out-of-stock' | 'valid' | 'expired' | 'unknown';
type SortKey = 'name' | 'vendor' | 'category' | 'availability' | 'price';

const STATUS_META: Record<Status, { label: string; dot: string }> = {
  'in-stock': { label: 'In stock', dot: 'bg-green-500' },
  'out-of-stock': { label: 'Out of stock', dot: 'bg-red-500' },
  valid: { label: 'Valid offer', dot: 'bg-violet-500' },
  expired: { label: 'Expired offer', dot: 'bg-rose-500' },
  unknown: { label: 'Availability unknown', dot: 'bg-gray-400' },
};

const categoryLabel = (category: string) =>
  category === 'medicine' ? 'Medicine' : category === 'equipment' ? 'Equipment' : 'Other';

function statusOf(article: CatalogueArticle): Status {
  if (article.source === 'erp') {
    if (article.stock === null) return 'unknown';
    return Number(article.stock) > 0 ? 'in-stock' : 'out-of-stock';
  }
  if (!article.valid_until) return 'unknown';
  return article.valid_until < new Date().toLocaleDateString('sv-SE') ? 'expired' : 'valid';
}

function formatPrice(price: string, currency: string | null): string {
  const amount = Number(price);
  if (!currency || !/^[A-Z]{3}$/.test(currency)) return `${amount.toLocaleString()} ${currency || ''}`.trim();
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
  } catch {
    return `${amount.toLocaleString()} ${currency}`;
  }
}

function compareArticles(a: CatalogueArticle, b: CatalogueArticle, key: SortKey): number {
  if (key === 'price') return (a.price === null ? Infinity : Number(a.price)) - (b.price === null ? Infinity : Number(b.price));
  if (key === 'availability') {
    const value = (article: CatalogueArticle) => article.source === 'erp'
      ? article.stock === null ? -Infinity : Number(article.stock) + 1e13
      : article.valid_until ? Date.parse(article.valid_until) : -Infinity;
    return value(a) - value(b);
  }
  if (key === 'category') return categoryLabel(a.category).localeCompare(categoryLabel(b.category)) || a.name.localeCompare(b.name);
  return (key === 'vendor' ? a.vendor ?? '' : a.name).localeCompare(key === 'vendor' ? b.vendor ?? '' : b.name);
}

function SortHeader({ label, sortKey, activeKey, direction, onSort, align }: {
  label: string; sortKey?: SortKey; activeKey: SortKey; direction: 1 | -1;
  onSort: (key: SortKey) => void; align?: 'right';
}) {
  const active = sortKey === activeKey;
  const Icon = active ? direction === 1 ? ArrowUp : ArrowDown : ArrowUpDown;
  return <th className={`sticky top-0 z-10 border-b border-gray-200 bg-gray-50 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider ${align === 'right' ? 'text-right' : 'text-left'}`}>
    {sortKey ? <button type="button" onClick={() => onSort(sortKey)} className={`inline-flex items-center gap-1 uppercase tracking-wider ${active ? 'text-[#1B4E8A]' : 'text-gray-500 hover:text-gray-800'}`}>
      {label}<Icon size={11} className={active ? '' : 'opacity-40'} />
    </button> : <span className="text-gray-500">{label}</span>}
  </th>;
}

export function CatalogueScreen() {
  const [articles, setArticles] = useState<CatalogueArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState('');
  const [source, setSource] = useState<SourceFilter>('all');
  const [category, setCategory] = useState('all');
  const [statuses, setStatuses] = useState<Set<Status>>(new Set());
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'name', dir: 1 });

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getCatalogueArticles(controller.signal)
      .then(setArticles)
      .catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not load the catalogue.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);

  const erpCount = articles.filter(article => article.source === 'erp').length;
  const categories = [...new Set(articles.map(article => categoryLabel(article.category)))].sort();
  const statusCounts = Object.fromEntries(
    (Object.keys(STATUS_META) as Status[]).map(status => [status, articles.filter(article => statusOf(article) === status).length]),
  ) as Record<Status, number>;
  const rows = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    return articles.filter(article =>
      (source === 'all' || article.source === source)
      && (category === 'all' || categoryLabel(article.category) === category)
      && (statuses.size === 0 || statuses.has(statusOf(article)))
      && (!term || [article.name, article.vendor, article.reference, article.category]
        .some(value => value?.toLocaleLowerCase().includes(term))),
    ).sort((a, b) => {
      const difference = compareArticles(a, b, sort.key);
      return (Number.isNaN(difference) ? 0 : difference) * sort.dir || a.id.localeCompare(b.id);
    });
  }, [articles, query, source, category, statuses, sort]);
  const filtersActive = query !== '' || source !== 'all' || category !== 'all' || statuses.size > 0;
  const resetFilters = () => { setQuery(''); setSource('all'); setCategory('all'); setStatuses(new Set()); };
  const toggleStatus = (status: Status) => setStatuses(previous => {
    const next = new Set(previous);
    if (next.has(status)) next.delete(status); else next.add(status);
    return next;
  });
  const onSort = (key: SortKey) => setSort(previous => ({ key, dir: previous.key === key && previous.dir === 1 ? -1 : 1 }));

  return <div className="flex min-h-full flex-col p-4 sm:p-6">
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-gray-900">Article Catalogue</h1>
        <p className="mt-0.5 text-sm text-gray-500">ERP articles and supplier offers from SharePoint, in one list.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" disabled title="Fetching new data is coming later" className="mr-1 inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg bg-[#1B4E8A] px-3 py-1.5 font-semibold text-white opacity-50">
          <RefreshCw size={13} /> Fetch new data
        </button>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-2.5 py-1 font-semibold text-blue-700"><Database size={11} /> {erpCount} ERP articles</span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-100 px-2.5 py-1 font-semibold text-violet-700"><FileText size={11} /> {articles.length - erpCount} supplier offers</span>
      </div>
    </div>

    {error && <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      Could not load the catalogue: {error} <button type="button" onClick={() => setReload(value => value + 1)} className="ml-2 font-semibold underline">Try again</button>
    </div>}

    <div className="space-y-3 rounded-t-xl border border-b-0 border-gray-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[240px] flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search name, supplier, ERP ID or offer file…" aria-label="Search articles" className="w-full rounded-lg border border-gray-200 bg-gray-50 py-2 pl-9 pr-8 text-sm focus:border-[#1B4E8A] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#1B4E8A]/20" />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"><X size={14} /></button>}
        </div>
        <div className="inline-flex rounded-lg bg-gray-100 p-0.5">
          {([{ value: 'all', label: 'All', count: articles.length }, { value: 'erp', label: 'ERP', count: erpCount }, { value: 'sharepoint', label: 'Offers', count: articles.length - erpCount }] as const).map(option =>
            <button key={option.value} type="button" aria-pressed={source === option.value} onClick={() => setSource(option.value)} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${source === option.value ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}>
              {option.label} <span className="ml-1 font-medium text-gray-400">{option.count}</span>
            </button>,
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button type="button" onClick={() => setCategory('all')} className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold underline-offset-4 ${category === 'all' ? 'text-[#1B4E8A] underline decoration-2' : 'text-gray-400 hover:text-gray-700'}`}>All categories</button>
          {categories.map(value => <button key={value} type="button" aria-pressed={category === value} onClick={() => setCategory(category === value ? 'all' : value)} className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${category === value ? 'border-[#1B4E8A] bg-[#1B4E8A] text-white' : 'border-gray-200 text-gray-600 hover:border-gray-400'}`}>
            {value} <span className={category === value ? 'text-white/70' : 'text-gray-400'}>{articles.filter(article => categoryLabel(article.category) === value).length}</span>
          </button>)}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</span>
        {(Object.keys(STATUS_META) as Status[]).filter(status => statusCounts[status] > 0).map(status => {
          const selected = statuses.has(status);
          return <button key={status} type="button" aria-pressed={selected} onClick={() => toggleStatus(status)} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${selected ? 'border-[#1B4E8A] bg-[#1B4E8A] text-white' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${selected ? 'bg-white' : STATUS_META[status].dot}`} /> {STATUS_META[status].label} <span className={selected ? 'text-white/70' : 'text-gray-400'}>{statusCounts[status]}</span>
          </button>;
        })}
        <div className="ml-auto flex items-center gap-3 text-xs text-gray-500"><span><strong className="text-gray-900">{rows.length}</strong> of {articles.length} articles</span>{filtersActive && <button type="button" onClick={resetFilters} className="font-semibold text-[#1B4E8A] hover:underline">Clear filters</button>}</div>
      </div>
    </div>

    <div className="min-h-[300px] flex-1 overflow-auto rounded-b-xl border border-gray-200 bg-white">
      <table className="w-full min-w-[900px]">
        <thead><tr>
          <SortHeader label="Article" sortKey="name" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Source" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Manufacturer / Supplier" sortKey="vendor" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Category" sortKey="category" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="ERP ID / Offer" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Availability" sortKey="availability" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Unit price" sortKey="price" activeKey={sort.key} direction={sort.dir} onSort={onSort} align="right" />
        </tr></thead>
        <tbody>{rows.map(article => {
          const offer = article.source === 'sharepoint';
          const expired = statusOf(article) === 'expired';
          return <tr key={article.id} className={`border-b ${expired ? 'border-rose-100 bg-rose-50/30 hover:bg-rose-50/60' : offer ? 'border-violet-100 bg-violet-50/30 hover:bg-violet-50/70' : 'border-gray-100 hover:bg-gray-50'}`}>
            <td className={`border-l-[3px] px-4 py-3 ${expired ? 'border-l-rose-500' : offer ? 'border-l-violet-500' : 'border-l-transparent'}`}><span className={`text-sm font-semibold ${expired ? 'text-gray-500' : 'text-gray-900'}`}>{article.name}</span>{article.embedded && <span className="ml-2 whitespace-nowrap rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">Embedded</span>}</td>
            <td className="px-4 py-3">{offer ? <span className="inline-flex items-center gap-1 rounded bg-violet-100 px-1.5 py-0.5 text-[11px] font-bold text-violet-700"><FileText size={10} /> OFFER</span> : <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-bold text-blue-700"><Database size={10} /> ERP</span>}</td>
            <td className="px-4 py-3 text-xs text-gray-600">{article.vendor || '—'}</td>
            <td className="px-4 py-3 text-xs text-gray-500">{categoryLabel(article.category)}</td>
            <td className="px-4 py-3">{offer && article.source_url ? <a href={article.source_url} target="_blank" rel="noopener noreferrer" title={`Open ${article.reference} in SharePoint`} className="inline-flex max-w-[200px] items-center gap-1.5 text-xs font-medium text-violet-800 hover:text-violet-950"><FileText size={12} className="shrink-0 text-violet-500" /><span className="truncate hover:underline">{article.reference}</span><ExternalLink size={10} className="shrink-0 opacity-60" /></a> : <span className="font-mono text-xs text-gray-500">{article.reference}</span>}</td>
            <td className="whitespace-nowrap px-4 py-3 text-xs">{offer ? expired ? <span className="inline-flex items-center gap-1 font-semibold text-rose-600"><CalendarX2 size={11} /> Expired {article.valid_until}</span> : article.valid_until ? <span className="font-medium text-violet-700">Offer · valid to {article.valid_until}</span> : <span className="text-gray-500">Validity unknown</span> : article.stock === null ? <span className="text-gray-500">Stock unavailable</span> : <span className={Number(article.stock) > 0 ? 'font-semibold text-green-700' : 'font-semibold text-red-600'}>{Number(article.stock).toLocaleString()} {article.unit || 'units'}</span>}</td>
            <td className="whitespace-nowrap px-4 py-3 text-right text-sm">{article.price === null ? <span className="text-xs italic text-gray-400">{offer ? 'On request' : '—'}</span> : <span className={`font-semibold ${expired ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{formatPrice(article.price, article.currency)}<span className="text-xs font-normal text-gray-400">{article.unit ? ` / ${article.unit}` : ''}</span></span>}</td>
          </tr>;
        })}</tbody>
      </table>
      {!loading && !error && rows.length === 0 && <div className="flex flex-col items-center py-16 text-center"><PackageSearch size={32} className="mb-3 text-gray-300" /><div className="text-sm font-semibold text-gray-700">{filtersActive ? 'No articles match these filters' : 'No articles stored yet'}</div>{filtersActive && <button type="button" onClick={resetFilters} className="mt-2 text-sm font-semibold text-[#1B4E8A] hover:underline">Clear filters</button>}</div>}
      {loading && <div role="status" className="py-16 text-center text-sm text-gray-500">Loading articles…</div>}
    </div>
  </div>;
}
