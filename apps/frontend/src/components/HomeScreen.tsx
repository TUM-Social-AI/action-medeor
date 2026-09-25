import { useEffect, useState, type ReactNode } from 'react';
import { ArrowRight, CheckCircle2, Clock, FileText, LayoutDashboard, Package, Plus, Star, TrendingUp, Users } from 'lucide-react';
import { getHome } from '../api/client';
import type { HomeResponse, HomeStat } from '../api/types';
import { listRequests, type SavedRequest } from '../api/workflow';
import { ErrorPanel, LoadingPanel } from './ScreenState';

type Props = {
  onCreateRequest: () => void;
  onOpenRequest: (request: SavedRequest) => void;
  onViewDashboard: () => void;
  onViewHistory: () => void;
  history?: boolean;
  error?: string | null;
};

const STAT_ICON: Record<string, { icon: ReactNode; bg: string; highlight?: boolean }> = {
  requests_processed: { icon: <FileText size={17} className="text-[#1B4E8A]" />, bg: 'bg-blue-100' },
  items_matched: { icon: <Package size={17} className="text-[#0E9E8F]" />, bg: 'bg-teal-100' },
  overall_match_rate: { icon: <Star size={17} className="text-green-600" />, bg: 'bg-green-100', highlight: true },
  partner_organizations: { icon: <Users size={17} className="text-purple-600" />, bg: 'bg-purple-100' },
  avg_processing_time: { icon: <Clock size={17} className="text-amber-600" />, bg: 'bg-amber-100' },
};

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function RequestTable({ requests, loading, onOpenRequest }: {
  requests: SavedRequest[] | null;
  loading: boolean;
  onOpenRequest: Props['onOpenRequest'];
}) {
  return <div className="overflow-x-auto">
    <table className="w-full min-w-[780px]">
      <thead><tr className="border-b border-gray-100 bg-gray-50/60">
        {['Request ID', 'Partner Organization', 'Region', 'Date', 'Items', 'Match Rate', 'Status'].map(header =>
          <th key={header} className="text-left px-5 py-2.5 text-xs text-gray-500 uppercase tracking-wide font-semibold">{header}</th>,
        )}
      </tr></thead>
      <tbody>
        {loading && <tr><td colSpan={7} className="p-5"><LoadingPanel label="Loading requests" /></td></tr>}
        {!loading && requests?.length === 0 && <tr><td colSpan={7} className="p-6 text-sm text-gray-500">No requests yet.</td></tr>}
        {requests?.map(request => <tr
          key={request.requestId}
          role="button"
          tabIndex={0}
          aria-label={`Open request ${request.requestId}`}
          onClick={() => onOpenRequest(request)}
          onKeyDown={event => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              onOpenRequest(request);
            }
          }}
          className={'border-b border-gray-100 last:border-0 transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-[#1B4E8A] ' + (request.status === 'finalized' ? 'bg-green-50/60 hover:bg-green-100/60' : 'hover:bg-gray-50')}
        >
          <td className="px-5 py-3.5 text-sm font-mono text-[#1B4E8A] font-semibold" title={request.sourceFile || ''}>{request.requestId}</td>
          <td className="px-5 py-3.5 text-sm text-gray-900 font-medium">{request.partner || 'Not specified'}</td>
          <td className="px-5 py-3.5 text-sm text-gray-500">{request.region || '—'}</td>
          <td className="px-5 py-3.5 text-sm text-gray-500">{formatDate(request.createdAt)}</td>
          <td className="px-5 py-3.5 text-sm text-gray-900 font-medium">{request.itemCount}</td>
          <td className="px-5 py-3.5 text-sm font-bold">
            {request.matchRate === null ? <span className="text-gray-400">—</span> :
              <span className={request.matchRate >= 90 ? 'text-green-700' : request.matchRate >= 80 ? 'text-amber-600' : 'text-red-600'}>{request.matchRate}%</span>}
          </td>
          <td className="px-5 py-3.5">
            <span className={'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ' + (request.status === 'finalized' ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700')}>
              {request.status === 'finalized' && <CheckCircle2 size={11} />}
              {request.status.replace(/_/g, ' ')}
            </span>
          </td>
        </tr>)}
      </tbody>
    </table>
  </div>;
}

export function HomeScreen({ onCreateRequest, onOpenRequest, onViewDashboard, onViewHistory, history, error }: Props) {
  const [requests, setRequests] = useState<SavedRequest[] | null>(null);
  const [home, setHome] = useState<HomeResponse | null>(null);
  const [homeError, setHomeError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listRequests()
      .then(value => { if (active) { setRequests(value); setLoadError(null); } })
      .catch(caught => { if (active) setLoadError(String(caught)); });
    if (!history) {
      getHome()
        .then(value => { if (active) { setHome(value); setHomeError(null); } })
        .catch(caught => { if (active) setHomeError(String(caught)); });
    }
    return () => { active = false; };
  }, [history]);

  if (history) return <div className="p-6 max-w-6xl mx-auto">
    <div className="flex items-center justify-between mb-6">
      <div><h1 className="text-gray-900">Request History</h1><p className="text-sm text-gray-500">Reopen saved extraction and matching work.</p></div>
      <button onClick={onCreateRequest} className="flex items-center gap-2 px-5 py-3 bg-[#1B4E8A] text-white rounded-xl"><Plus size={16} /> New Request</button>
    </div>
    {(error || loadError) && <div className="mb-4"><ErrorPanel message={error || loadError || ''} /></div>}
    {!loadError && <div className="bg-white rounded-xl border border-gray-200 overflow-hidden"><RequestTable requests={requests} loading={!requests} onOpenRequest={onOpenRequest} /></div>}
  </div>;

  return <div className="p-6 max-w-6xl mx-auto">
    <div className="mb-6">
      <h1 className="text-gray-900">Welcome back, {home?.userName ?? 'Leon'}</h1>
      <p className="text-gray-500 text-sm mt-0.5">
        {home?.organization ?? 'action medeor'} - Procurement Operations -{' '}
        {new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
      </p>
    </div>

    {error && <div className="mb-4"><ErrorPanel message={error} /></div>}
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-7">
      <button onClick={onCreateRequest} className="lg:col-span-2 text-left bg-[#1B4E8A] rounded-2xl p-8 cursor-pointer hover:bg-[#163d6d] transition-all shadow-lg group select-none">
        <div className="w-13 h-13 rounded-xl bg-white/15 flex items-center justify-center mb-5" style={{ width: 52, height: 52 }}><FileText size={26} className="text-white" /></div>
        <div className="text-white text-xl mb-2 font-bold">Create New Request</div>
        <p className="text-white/70 text-sm leading-relaxed" style={{ maxWidth: 380 }}>
          Upload a partner request file and start the AI-assisted matching workflow. Supports PDF, Excel (.xlsx, .xls), Word (.docx), and CSV formats.
        </p>
        <div className="mt-6 inline-flex items-center gap-2 bg-white/15 hover:bg-white/25 transition-colors px-4 py-2.5 rounded-lg text-white text-sm font-semibold">
          Start workflow <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform" />
        </div>
      </button>
      <button onClick={onViewDashboard} className="text-left bg-violet-50/30 rounded-2xl p-6 border border-violet-100 cursor-pointer hover:border-[#0E9E8F]/50 hover:shadow-md transition-all group flex flex-col justify-between select-none">
        <div>
          <div className="w-11 h-11 rounded-xl bg-teal-50 flex items-center justify-center mb-4"><LayoutDashboard size={21} className="text-[#0E9E8F]" /></div>
          <div className="text-gray-900 text-base mb-2 font-bold">Trend Dashboard</div>
          <p className="text-gray-500 text-sm leading-relaxed">Demand analytics, regional insights, and category trends informed by partner requests and offers sent.</p>
        </div>
        <div className="mt-5 flex items-center gap-1 text-[#0E9E8F] text-sm font-semibold">View dashboard <ArrowRight size={13} className="group-hover:translate-x-0.5 transition-transform" /></div>
      </button>
    </div>

    <div className="flex items-center gap-2 mb-3"><span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Overview</span><span className="text-xs font-medium text-violet-700 bg-violet-100/70 border border-violet-200/60 rounded-full px-2 py-0.5">Sample data</span></div>
    {homeError && <div className="mb-6"><ErrorPanel message={homeError} /></div>}
    {!home && !homeError && <div className="mb-6"><LoadingPanel label="Loading home data" /></div>}
    {home && <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-6">{home.stats.map(stat => <StatCard key={stat.key} stat={stat} />)}</div>}

    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2"><Clock size={15} className="text-gray-400" /><span className="text-sm text-gray-900 font-semibold">Recent Requests</span></div>
        <button onClick={onViewHistory} className="text-sm text-[#1B4E8A] hover:underline font-medium">View all history</button>
      </div>
      {loadError ? <div className="p-5"><ErrorPanel message={loadError} /></div> : <RequestTable requests={requests?.slice(0, 6) ?? null} loading={!requests} onOpenRequest={onOpenRequest} />}
    </div>
  </div>;
}

function StatCard({ stat }: { stat: HomeStat }) {
  const visual = STAT_ICON[stat.key] ?? { icon: <TrendingUp size={17} className="text-[#1B4E8A]" />, bg: 'bg-blue-100' };
  return <div className="bg-violet-50/30 rounded-xl border border-violet-100 p-5">
    <div className="flex items-center justify-between mb-3"><div className={`w-9 h-9 rounded-lg ${visual.bg} flex items-center justify-center`}>{visual.icon}</div></div>
    <div className={`text-2xl ${visual.highlight ? 'text-[#0E9E8F]' : 'text-gray-900'}`} style={{ fontWeight: 800 }}>{stat.value}</div>
    <div className="text-xs text-gray-700 mt-1 font-semibold">{stat.label}</div>
    <div className="text-xs text-gray-400">{stat.sub}</div>
  </div>;
}
