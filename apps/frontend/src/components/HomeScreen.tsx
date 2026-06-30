import { useEffect, useState, type ReactNode } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  FileText,
  LayoutDashboard,
  Package,
  Star,
  TrendingUp,
  Users,
} from 'lucide-react';
import { getHome } from '../api/client';
import type { HomeResponse, HomeStat } from '../api/types';
import { ErrorPanel, LoadingPanel } from './ScreenState';

type HomeScreenProps = {
  onCreateRequest: () => void;
  onViewDashboard: () => void;
};

const STAT_ICON: Record<string, { icon: ReactNode; bg: string; highlight?: boolean }> = {
  requests_processed: {
    icon: <FileText size={17} className="text-[#1B4E8A]" />,
    bg: 'bg-blue-100',
  },
  items_matched: {
    icon: <Package size={17} className="text-[#0E9E8F]" />,
    bg: 'bg-teal-100',
  },
  overall_match_rate: {
    icon: <Star size={17} className="text-green-600" />,
    bg: 'bg-green-100',
    highlight: true,
  },
  partner_organizations: {
    icon: <Users size={17} className="text-purple-600" />,
    bg: 'bg-purple-100',
  },
  avg_processing_time: {
    icon: <Clock size={17} className="text-amber-600" />,
    bg: 'bg-amber-100',
  },
};

export function HomeScreen({ onCreateRequest, onViewDashboard }: HomeScreenProps) {
  const [data, setData] = useState<HomeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    getHome()
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
      });

    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-gray-900">Welcome back, {data?.userName ?? 'Lea'}</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          {data?.organization ?? 'action medeor'} - Procurement Operations -{' '}
          {data?.currentDate ?? 'June 13, 2024'}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-5 mb-7">
        <button
          onClick={onCreateRequest}
          className="col-span-2 text-left bg-[#1B4E8A] rounded-2xl p-8 cursor-pointer hover:bg-[#163d6d] transition-all shadow-lg group select-none"
        >
          <div className="w-13 h-13 rounded-xl bg-white/15 flex items-center justify-center mb-5" style={{ width: 52, height: 52 }}>
            <FileText size={26} className="text-white" />
          </div>
          <div className="text-white text-xl mb-2" style={{ fontWeight: 700 }}>
            Create New Request
          </div>
          <p className="text-white/70 text-sm leading-relaxed" style={{ maxWidth: 380 }}>
            Upload a partner request file and start the AI-assisted matching workflow. Supports PDF
            and Excel formats (.xlsx, .xls).
          </p>
          <div
            className="mt-6 inline-flex items-center gap-2 bg-white/15 hover:bg-white/25 transition-colors px-4 py-2.5 rounded-lg text-white text-sm"
            style={{ fontWeight: 600 }}
          >
            Start workflow
            <ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform" />
          </div>
        </button>

        <button
          onClick={onViewDashboard}
          className="text-left bg-white rounded-2xl p-6 border border-gray-200 cursor-pointer hover:border-[#0E9E8F]/50 hover:shadow-md transition-all group flex flex-col justify-between select-none"
        >
          <div>
            <div className="w-11 h-11 rounded-xl bg-teal-50 flex items-center justify-center mb-4">
              <LayoutDashboard size={21} className="text-[#0E9E8F]" />
            </div>
            <div className="text-gray-900 text-base mb-2" style={{ fontWeight: 700 }}>
              Trend Dashboard
            </div>
            <p className="text-gray-500 text-sm leading-relaxed">
              Demand analytics, regional insights, and category trends informed by partner requests
              and offers sent.
            </p>
          </div>
          <div className="mt-5 flex items-center gap-1 text-[#0E9E8F] text-sm" style={{ fontWeight: 600 }}>
            View dashboard
            <ArrowRight size={13} className="group-hover:translate-x-0.5 transition-transform" />
          </div>
        </button>
      </div>

      {error && <ErrorPanel message={error} />}
      {!data && !error && <LoadingPanel label="Loading home data" />}

      {data && (
        <>
          <div className="grid grid-cols-5 gap-4 mb-6">
            {data.stats.map(stat => (
              <StatCard key={stat.key} stat={stat} />
            ))}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Clock size={15} className="text-gray-400" />
                <span className="text-sm text-gray-900" style={{ fontWeight: 600 }}>
                  Recent Requests
                </span>
              </div>
              <button className="text-sm text-[#1B4E8A] hover:underline" style={{ fontWeight: 500 }}>
                View all history
              </button>
            </div>
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/60">
                  {['Request ID', 'Partner Organization', 'Region', 'Date', 'Items', 'Match Rate', 'Status'].map(header => (
                    <th
                      key={header}
                      className="text-left px-5 py-2.5 text-xs text-gray-500"
                      style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.recentRequests.map(request => (
                  <tr
                    key={request.id}
                    className="border-b border-gray-100 hover:bg-gray-50 transition-colors cursor-pointer"
                  >
                    <td className="px-5 py-3.5 text-sm font-mono text-[#1B4E8A]" style={{ fontWeight: 600 }}>
                      {request.id}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-900" style={{ fontWeight: 500 }}>
                      {request.partner}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-gray-500">{request.region}</td>
                    <td className="px-5 py-3.5 text-sm text-gray-500">{request.date}</td>
                    <td className="px-5 py-3.5 text-sm text-gray-900" style={{ fontWeight: 500 }}>
                      {request.items}
                    </td>
                    <td className="px-5 py-3.5">
                      <span
                        className={`text-sm ${
                          request.matchRate >= 90
                            ? 'text-green-700'
                            : request.matchRate >= 80
                              ? 'text-amber-600'
                              : 'text-red-600'
                        }`}
                        style={{ fontWeight: 700 }}
                      >
                        {request.matchRate}%
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs"
                        style={{ fontWeight: 500 }}
                      >
                        <CheckCircle2 size={11} />
                        {request.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ stat }: { stat: HomeStat }) {
  const visual = STAT_ICON[stat.key] ?? {
    icon: <TrendingUp size={17} className="text-[#1B4E8A]" />,
    bg: 'bg-blue-100',
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className={`w-9 h-9 rounded-lg ${visual.bg} flex items-center justify-center`}>
          {visual.icon}
        </div>
      </div>
      <div
        className={`text-2xl ${visual.highlight ? 'text-[#0E9E8F]' : 'text-gray-900'}`}
        style={{ fontWeight: 800 }}
      >
        {stat.value}
      </div>
      <div className="text-xs text-gray-700 mt-1" style={{ fontWeight: 600 }}>
        {stat.label}
      </div>
      <div className="text-xs text-gray-400">{stat.sub}</div>
    </div>
  );
}

