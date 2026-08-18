import { useEffect, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  FileText,
  Package,
  Star,
  TrendingUp,
  Users,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getTrends } from '../api/client';
import type { CategoryDemand, KpiCard, TrendsResponse } from '../api/types';
import { ErrorPanel, LoadingPanel } from './ScreenState';

const KPI_VISUALS: Record<string, { icon: ReactNode; bg: string }> = {
  requests_processed: {
    icon: <FileText size={16} className="text-[#1B4E8A]" />,
    bg: 'bg-blue-100',
  },
  items_matched: {
    icon: <Package size={16} className="text-[#0E9E8F]" />,
    bg: 'bg-teal-100',
  },
  overall_match_rate: {
    icon: <Star size={16} className="text-green-600" />,
    bg: 'bg-green-100',
  },
  partner_organizations: {
    icon: <Users size={16} className="text-purple-600" />,
    bg: 'bg-purple-100',
  },
  items_flagged: {
    icon: <AlertCircle size={16} className="text-amber-600" />,
    bg: 'bg-amber-100',
  },
  demand_growth: {
    icon: <TrendingUp size={16} className="text-red-500" />,
    bg: 'bg-red-100',
  },
};

const RISK_STYLES = {
  critical: { bar: 'bg-red-500', text: 'text-red-600' },
  high: { bar: 'bg-amber-500', text: 'text-amber-600' },
  medium: { bar: 'bg-[#0E9E8F]', text: 'text-teal-600' },
};

const LINE_COLORS = {
  antibiotics: { color: '#1B4E8A', label: 'Antibiotics' },
  analgesics: { color: '#0E9E8F', label: 'Analgesics' },
  trauma: { color: '#D97706', label: 'Trauma & Wound' },
  ivFluids: { color: '#6366F1', label: 'IV Fluids' },
};

export function TrendDashboard() {
  const [data, setData] = useState<TrendsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    getTrends()
      .then(response => {
        if (mounted) {
          setData(response);
          setError(null);
        }
      })
      .catch(caught => {
        if (mounted) {
          setError(caught instanceof Error ? caught.message : 'Unable to reach backend');
        }
      })
      .finally(() => {
        if (mounted) {
          setIsLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  if (isLoading) {
    return (
      <div className="p-6">
        <LoadingPanel label="Loading procurement trends" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6">
        <ErrorPanel message={error ?? 'Trend data is unavailable'} />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-gray-900">Trend Dashboard</h1>
        <div className="flex items-center gap-3 mt-1">
          <p className="text-gray-500 text-sm">
            Demand analytics derived from partner requests and offers - action medeor global
            operations.
          </p>
          <span className="text-xs text-gray-400 border border-gray-200 rounded-full px-2 py-0.5 flex-shrink-0">
            {data.asOf}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-6 gap-4 mb-6">
        {data.kpis.map(kpi => (
          <KpiTile key={kpi.key} kpi={kpi} />
        ))}
      </div>

      <div className="grid grid-cols-3 gap-5 mb-5">
        <div className="col-span-2 bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
                Items Requested by Category
              </div>
              <div className="text-xs text-gray-400">
                Monthly item quantities from partner requests - Jan-Jun 2024
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {Object.values(LINE_COLORS).map(line => (
                <div key={line.label} className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: line.color }} />
                  <span className="text-xs text-gray-500">{line.label}</span>
                </div>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={data.demandTrend} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  border: '1px solid #E5E7EB',
                  borderRadius: 8,
                  boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)',
                }}
                formatter={(value: number, name: string) => {
                  const label = LINE_COLORS[name as keyof typeof LINE_COLORS]?.label ?? name;
                  return [value.toLocaleString() + ' units', label];
                }}
              />
              {Object.entries(LINE_COLORS).map(([key, line]) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={line.color}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: line.color, strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="mb-4">
            <div className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
              Category Demand & Growth
            </div>
            <div className="text-xs text-gray-400">Total items requested YTD - YoY change</div>
          </div>
          <div className="space-y-3.5">
            {data.categoryDemand.map(category => (
              <CategoryRow key={category.name} category={category} />
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-5">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="mb-4">
            <div className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
              Requests by Destination Region
            </div>
            <div className="text-xs text-gray-400">
              Number of requests received per crisis area - Jan-Jun 2024
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.regionalDemand} margin={{ top: 0, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" vertical={false} />
              <XAxis dataKey="region" tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ fontSize: 12, border: '1px solid #E5E7EB', borderRadius: 8 }}
                formatter={(value: number) => [value, 'Requests']}
              />
              <Bar dataKey="requests" fill="#1B4E8A" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {data.regionalDemand.slice(0, 3).map(region => (
              <div key={region.region} className="bg-gray-50 rounded-lg p-2.5 border border-gray-100">
                <div className="text-xs text-gray-700" style={{ fontWeight: 600 }}>
                  {region.region}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{region.requests} requests</div>
                <div className="text-xs text-[#1B4E8A]" style={{ fontWeight: 600 }}>
                  {region.items} items
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="mb-4">
            <div className="text-sm text-gray-900" style={{ fontWeight: 700 }}>
              Most Requested Items
            </div>
            <div className="text-xs text-gray-400">
              Frequency across all partner requests - YTD demand trend
            </div>
          </div>
          <div className="space-y-2.5">
            {data.topItems.map((item, index) => (
              <div key={item.name} className="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0">
                <div className="w-6 h-6 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0 text-xs text-gray-500" style={{ fontWeight: 700 }}>
                  {index + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-gray-900 truncate" style={{ fontWeight: 600 }}>
                    {item.name}
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {item.requests} requests - {item.totalQty.toLocaleString()} units total
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <ArrowUpRight size={12} className="text-green-500" />
                  <span className="text-xs text-green-600" style={{ fontWeight: 700 }}>
                    +{item.trend}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function KpiTile({ kpi }: { kpi: KpiCard }) {
  const visual = KPI_VISUALS[kpi.key] ?? KPI_VISUALS.requests_processed;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-2">
        <span
          className="text-xs text-gray-400 leading-tight"
          style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}
        >
          {kpi.label}
        </span>
        <div className={`w-7 h-7 rounded-lg ${visual.bg} flex items-center justify-center flex-shrink-0`}>
          {visual.icon}
        </div>
      </div>
      <div className="text-xl text-gray-900" style={{ fontWeight: 800 }}>
        {kpi.value}
      </div>
      <div className="flex items-center gap-1 mt-0.5">
        {kpi.up ? (
          <ArrowUpRight size={12} className="text-green-500" />
        ) : (
          <ArrowDownRight size={12} className="text-amber-500" />
        )}
        <span className={`text-xs ${kpi.up ? 'text-green-600' : 'text-amber-600'}`} style={{ fontWeight: 600 }}>
          {kpi.delta}
        </span>
      </div>
      <div className="text-xs text-gray-400 mt-0.5">{kpi.sub}</div>
    </div>
  );
}

function CategoryRow({ category }: { category: CategoryDemand }) {
  const style = RISK_STYLES[category.risk];

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="text-xs text-gray-800 truncate mr-2" style={{ fontWeight: 500 }}>
          {category.name}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <ArrowUpRight size={11} className={style.text} />
          <span className={`text-xs ${style.text}`} style={{ fontWeight: 700 }}>
            +{category.change}%
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${style.bar}`} style={{ width: `${(category.items / 25000) * 100}%` }} />
        </div>
        <span className="text-xs text-gray-400 w-12 text-right flex-shrink-0">
          {(category.items / 1000).toFixed(1)}k
        </span>
      </div>
    </div>
  );
}

