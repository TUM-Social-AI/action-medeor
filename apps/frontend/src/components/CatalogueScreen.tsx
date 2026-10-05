import { useEffect, useMemo, useState } from 'react';
import {
  ArrowDown, ArrowUp, ArrowUpDown, CalendarX2, Database, ExternalLink,
  FileText, PackageSearch, PauseCircle, RefreshCw, Search, Upload, X,
} from 'lucide-react';
import { getCatalogueArticles, type CatalogueArticle } from '../api/catalogue';
import {
  availableStatuses, categoryLabel, changeSource, DEFAULT_FILTERS, getCatalogueView,
  selectStatus, statusOf, type CatalogueFilters, type Status,
} from '../features/catalogue/filtering';
import { berlinDay, formatOfferPrice, getOfferStatus } from '../features/matching/offer-display';
import { useOfferDateRefresh } from '../features/matching/use-offer-date-refresh';
import { CatalogueImportDialog } from './CatalogueImportDialog';

type SortKey = 'name' | 'vendor' | 'category' | 'availability' | 'price';

const STATUS_META: Record<Status, { label: string; dot: string }> = {
  'in-stock': { label: 'In stock', dot: 'bg-green-500' },
  'out-of-stock': { label: 'Out of stock', dot: 'bg-red-500' },
  valid: { label: 'Valid offer', dot: 'bg-violet-500' },
  expired: { label: 'Expired offer', dot: 'bg-rose-500' },
  unknown: { label: 'Availability unknown', dot: 'bg-gray-400' },
  suspended: { label: 'Suspended', dot: 'bg-slate-500' },
  master: { label: 'Stammartikel', dot: 'bg-slate-400' },
};

function compareArticles(a: CatalogueArticle, b: CatalogueArticle, key: SortKey): number {
  if (key === 'price') {
    const value = (article: CatalogueArticle) => article.unit_price ?? article.price;
    return (value(a) == null ? Infinity : Number(value(a))) - (value(b) == null ? Infinity : Number(value(b)));
  }
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
  return <th className={`sticky top-0 z-10 border-b border-gray-200 bg-gray-50 px-3 py-3 text-[11px] font-semibold uppercase tracking-wider ${align === 'right' ? 'text-right' : 'text-left'}`}>
    {sortKey ? <button type="button" onClick={() => onSort(sortKey)} className={`inline-flex max-w-full items-center gap-1 text-left uppercase tracking-wider ${active ? 'text-[#1B4E8A]' : 'text-gray-500 hover:text-gray-800'}`}>
      <span>{label}</span><Icon size={11} className={`shrink-0 ${active ? '' : 'opacity-40'}`} />
    </button> : <span className="text-gray-500">{label}</span>}
  </th>;
}

export function CatalogueScreen() {
  const [articles, setArticles] = useState<CatalogueArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [filters, setFilters] = useState<CatalogueFilters>(DEFAULT_FILTERS);
  const { query, source, category, status } = filters;
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'name', dir: 1 });
  const [showImport, setShowImport] = useState(false);
  useOfferDateRefresh();
  const today = berlinDay(new Date());

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getCatalogueArticles(controller.signal)
      .then(data => { if (!controller.signal.aborted) setArticles(data); })
      .catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not load the catalogue.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);

  const view = useMemo(() => getCatalogueView(articles, filters, today), [articles, filters, today]);
  const { sourceCounts, statusCounts, categoryCounts, categories, visibleSourceCounts } = view;
  const rows = useMemo(() => {
    return [...view.rows].sort((a, b) => {
      const difference = compareArticles(a, b, sort.key);
      return (Number.isNaN(difference) ? 0 : difference) * sort.dir || a.id.localeCompare(b.id);
    });
  }, [view, sort]);
  const filtersActive = query.trim() !== '' || source !== 'all' || category !== 'all' || status !== 'all';
  const resetFilters = () => setFilters(DEFAULT_FILTERS);
  const setQuery = (query: string) => setFilters(previous => ({ ...previous, query }));
  const setCategory = (category: string) => setFilters(previous => ({ ...previous, category }));
  const onSort = (key: SortKey) => setSort(previous => ({ key, dir: previous.key === key && previous.dir === 1 ? -1 : 1 }));

  return <div className="flex min-h-full min-w-0 flex-col p-4 sm:p-6">
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-gray-900">Article Catalogue</h1>
        <p className="mt-0.5 text-sm text-gray-500">ERP articles and supplier offers from SharePoint, in one list.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={() => setShowImport(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-[#1B4E8A] px-3 py-1.5 font-semibold text-white hover:bg-[#163f70]">
          <Upload size={13} /> Update ERP catalogue
        </button>
        <button type="button" disabled title="Fetching new data is coming later" className="mr-1 inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg bg-[#1B4E8A] px-3 py-1.5 font-semibold text-white opacity-50">
          <RefreshCw size={13} /> Fetch new data
        </button>
        <span title="ERP articles matching the current filters" className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-2.5 py-1 font-semibold text-blue-700"><Database size={11} /> {visibleSourceCounts.erp} ERP articles</span>
        <span title="Supplier offers matching the current filters" className="inline-flex items-center gap-1.5 rounded-full bg-violet-100 px-2.5 py-1 font-semibold text-violet-700"><FileText size={11} /> {visibleSourceCounts.sharepoint} supplier offers</span>
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
        <div role="group" aria-label="Filter by source" className="inline-flex rounded-lg bg-gray-100 p-0.5">
          {([{ value: 'all', label: 'All' }, { value: 'erp', label: 'ERP' }, { value: 'sharepoint', label: 'Offers' }] as const).map(option =>
            <button key={option.value} type="button" aria-pressed={source === option.value} title="Counts match your search and category. Changing source resets status." onClick={() => setFilters(previous => changeSource(previous, option.value))} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${source === option.value ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}>
              {option.label} <span className="ml-1 font-medium text-gray-400">{sourceCounts[option.value]}</span>
            </button>,
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button type="button" aria-pressed={category === 'all'} onClick={() => setCategory('all')} className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold underline-offset-4 ${category === 'all' ? 'text-[#1B4E8A] underline decoration-2' : 'text-gray-400 hover:text-gray-700'}`}>All categories <span className="text-gray-400">{categoryCounts.all}</span></button>
          {categories.map(value => <button key={value} type="button" aria-pressed={category === value} disabled={categoryCounts[value] === 0 && category !== value} onClick={() => setCategory(category === value ? 'all' : value)} className={`rounded-full border px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-40 ${category === value ? 'border-[#1B4E8A] bg-[#1B4E8A] text-white' : 'border-gray-200 text-gray-600 hover:border-gray-400'}`}>
            {value} <span className={category === value ? 'text-white/70' : 'text-gray-400'}>{categoryCounts[value]}</span>
          </button>)}
        </div>
      </div>
      <div role="group" aria-label="Filter by status" className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</span>
        <button type="button" aria-pressed={status === 'all'} onClick={() => setFilters(previous => selectStatus(previous, 'all'))} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${status === 'all' ? 'border-[#1B4E8A] bg-[#1B4E8A] text-white' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}>All statuses <span className={status === 'all' ? 'text-white/70' : 'text-gray-400'}>{statusCounts.all}</span></button>
        {availableStatuses(source).map(option => {
          const selected = status === option;
          return <button key={option} type="button" aria-pressed={selected} disabled={statusCounts[option] === 0 && !selected} onClick={() => setFilters(previous => selectStatus(previous, option))} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 ${selected ? 'border-[#1B4E8A] bg-[#1B4E8A] text-white' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${selected ? 'bg-white' : STATUS_META[option].dot}`} /> {STATUS_META[option].label} <span className={selected ? 'text-white/70' : 'text-gray-400'}>{statusCounts[option]}</span>
          </button>;
        })}
        <div className="ml-auto flex items-center gap-3 text-xs text-gray-500"><span><strong className="text-gray-900">{rows.length}</strong> matching articles</span>{filtersActive && <button type="button" onClick={resetFilters} className="font-semibold text-[#1B4E8A] hover:underline">Clear filters</button>}</div>
      </div>
    </div>

    <div className="min-h-[300px] min-w-0 flex-1 overflow-auto rounded-b-xl border border-gray-200 bg-white">
      <table className="w-full min-w-[900px] table-fixed">
        <colgroup>
          <col className="w-[24%]" /><col className="w-[8%]" /><col className="w-[14%]" />
          <col className="w-[9%]" /><col className="w-[16%]" /><col className="w-[18%]" /><col className="w-[11%]" />
        </colgroup>
        <thead><tr>
          <SortHeader label="Article" sortKey="name" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Source" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Manufacturer / Supplier" sortKey="vendor" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Category" sortKey="category" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="ERP ID / Offer" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Availability" sortKey="availability" activeKey={sort.key} direction={sort.dir} onSort={onSort} />
          <SortHeader label="Price" sortKey="price" activeKey={sort.key} direction={sort.dir} onSort={onSort} align="right" />
        </tr></thead>
        <tbody>{rows.map(article => {
          const offer = article.source === 'sharepoint';
          const articleStatus = statusOf(article, today);
          const expired = articleStatus === 'expired';
          const offerStatus = offer ? getOfferStatus({
            offer_valid_until: articleStatus === 'unknown' ? null : article.valid_until,
            offer_date: article.offer_date,
            offer_date_source: article.offer_date_source,
            offer_validity_source: article.offer_validity_source,
          }) : null;
          const price = article.unit_price ?? article.price;
          const restricted = !offer && (article.blocked || article.sales_blocked || article.purchasing_blocked);
          const excluded = !offer && (article.blocked || article.sales_blocked);
          const hasStock = article.stock != null && article.stock.trim() !== '' && Number.isFinite(Number(article.stock));
          return <tr key={article.id} className={`border-b transition-colors ${restricted ? 'border-slate-200 bg-[repeating-linear-gradient(135deg,#f8fafc_0_8px,#f1f5f9_8px_16px)] hover:bg-slate-100' : expired ? 'border-rose-100 bg-rose-50/30 hover:bg-rose-50/60' : offer ? 'border-violet-100 bg-violet-50/30 hover:bg-violet-50/70' : 'border-gray-100 hover:bg-gray-50'}`}>
            <td className={`border-l-[3px] px-4 py-3 [overflow-wrap:anywhere] ${restricted ? 'border-l-slate-400 [border-left-style:dashed]' : expired ? 'border-l-rose-500' : offer ? 'border-l-violet-500' : 'border-l-transparent'}`}><span className={`text-sm font-semibold ${restricted ? 'text-slate-500' : expired ? 'text-gray-500' : 'text-gray-900'}`}>{article.name}</span>{article.embedded && !restricted && <span className="ml-2 whitespace-nowrap rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">Embedded</span>}
              {restricted && <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                {article.blocked && <span aria-label="Suspended" className="inline-flex items-center gap-1 rounded bg-slate-700 px-1.5 py-px text-[10px] font-bold tracking-wide text-white"><PauseCircle size={10} className="shrink-0" /> SUSPENDED</span>}
                {article.sales_blocked && <span className="rounded bg-slate-700 px-1.5 py-px text-[10px] font-bold text-white">Sales blocked</span>}
                {article.purchasing_blocked && <span title="Can only match requests fully covered by the available quantity" className="rounded bg-slate-200 px-1.5 py-px text-[10px] font-medium text-slate-600">Purchasing blocked</span>}
              </div>}
            </td>
            <td className="px-2 py-3">{offer ? <span className="inline-flex items-center gap-1 rounded bg-violet-100 px-1.5 py-0.5 text-[11px] font-bold text-violet-700"><FileText size={10} className="shrink-0" /> OFFER</span> : <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-bold ${restricted ? 'bg-slate-200 text-slate-500' : 'bg-blue-100 text-blue-700'}`}><Database size={10} className="shrink-0" /> ERP</span>}</td>
            <td className="px-4 py-3 text-xs text-gray-600 [overflow-wrap:anywhere]">{article.vendor || '—'}</td>
            <td className="px-3 py-3 text-xs text-gray-500 [overflow-wrap:anywhere]">{categoryLabel(article.category)}</td>
            <td className="px-4 py-3">{offer && article.source_url ? <a href={article.source_url} target="_blank" rel="noopener noreferrer" title={`Open ${article.reference} in SharePoint`} className="flex min-w-0 max-w-full items-center gap-1.5 text-xs font-medium text-violet-800 hover:text-violet-950"><FileText size={12} className="shrink-0 text-violet-500" /><span className="min-w-0 truncate hover:underline">{article.reference}</span><ExternalLink size={10} className="shrink-0 opacity-60" /></a> : <span title={article.reference} className={`block truncate font-mono text-xs ${excluded ? 'text-slate-400 line-through decoration-slate-300' : 'text-gray-500'}`}>{article.reference}</span>}</td>
            <td className="px-4 py-3 text-xs [overflow-wrap:anywhere]">{offerStatus ? <>
              <span className={`flex items-start gap-1 font-medium ${offerStatus.warning ? 'text-rose-600' : 'text-violet-700'}`}>
                {expired && <CalendarX2 size={11} className="mt-0.5 shrink-0" />} <span className="min-w-0">{offerStatus.label}</span>
              </span>
              {articleStatus === 'unknown' && <span className="mt-1 block text-gray-500">Validity unknown</span>}
            </> : article.master_item ? <span title="Base article for suffix variants; not sellable inventory" className="rounded bg-slate-100 px-2 py-1 font-medium text-slate-600">Stammartikel</span> : restricted ? <div className="leading-tight">
              <div className="font-semibold text-slate-600">{excluded ? 'Excluded from matching' : 'Stock-only matching'}</div>
              <div className="mt-0.5 text-[11px] text-slate-500">{hasStock ? `${Number(article.stock).toLocaleString()} ${article.unit || 'units'} available` : 'Stock unavailable'}</div>
            </div> : !hasStock ? <span className="text-gray-500">Stock unavailable</span> : <span className={Number(article.stock) > 0 ? 'font-semibold text-green-700' : 'font-semibold text-red-600'}>{Number(article.stock).toLocaleString()} {article.unit || 'units'}</span>}</td>
            <td className="px-4 py-3 text-right text-sm [overflow-wrap:anywhere]">{price == null ? <span className="text-xs italic text-gray-400">{offer ? 'On request' : '—'}</span> : <>
              <span className={`block font-semibold ${expired ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{formatOfferPrice(article.price, article.currency, article.price_basis, article.unit_price, article.unit_price_unit)}</span>
              {offer && <span className="mt-1 block text-xs text-gray-500">{article.unit_price != null ? 'Unit price' : 'Offer price'}</span>}
            </>}</td>
          </tr>;
        })}</tbody>
      </table>
      {!loading && !error && rows.length === 0 && <div className="flex flex-col items-center py-16 text-center"><PackageSearch size={32} className="mb-3 text-gray-300" /><div className="text-sm font-semibold text-gray-700">{filtersActive ? 'No articles match these filters' : 'No articles stored yet'}</div>{filtersActive && <button type="button" onClick={resetFilters} className="mt-2 text-sm font-semibold text-[#1B4E8A] hover:underline">Clear filters</button>}</div>}
      {loading && <div role="status" className="py-16 text-center text-sm text-gray-500">Loading articles…</div>}
    </div>
    {showImport && <CatalogueImportDialog onClose={() => setShowImport(false)} onUpdated={() => setReload(value => value + 1)} />}
  </div>;
}
