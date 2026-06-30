import type { ReactNode } from 'react';
import {
  Activity,
  ChevronRight,
  ClipboardList,
  Clock,
  FileText,
  GitMerge,
  HelpCircle,
  Home,
  LayoutDashboard,
  ListChecks,
  Settings,
  User,
} from 'lucide-react';
import type { Screen } from '../api/types';

type LayoutProps = {
  children: ReactNode;
  currentScreen: Screen;
  onNavigate: (screen: Screen) => void;
};

const SCREEN_LABELS: Record<Screen, string> = {
  home: 'Home',
  dashboard: 'Trend Dashboard',
  ingestion: 'Import Request',
  review: 'Review Items',
  matching: 'Smart Matching',
  summary: 'Order Summary',
};

const WORKFLOW_SCREENS: Screen[] = ['ingestion', 'review', 'matching', 'summary'];

export function Layout({ children, currentScreen, onNavigate }: LayoutProps) {
  const isWorkflow = WORKFLOW_SCREENS.includes(currentScreen);

  return (
    <div className="flex h-screen bg-[#F0F2F7] overflow-hidden">
      <aside className="w-56 bg-[#0F2044] flex flex-col flex-shrink-0 shadow-xl">
        <div className="h-16 flex items-center px-5 border-b border-white/10">
          <button
            onClick={() => onNavigate('home')}
            className="flex items-center gap-2.5 hover:opacity-80 transition-opacity"
          >
            <div className="w-8 h-8 rounded-lg bg-[#0E9E8F] flex items-center justify-center shadow-sm">
              <Activity size={16} className="text-white" />
            </div>
            <span className="text-white" style={{ fontWeight: 700, fontSize: 18 }}>
              Allocura
            </span>
          </button>
        </div>

        <div className="px-5 py-2.5 border-b border-white/10">
          <div className="text-white/40" style={{ fontSize: 11, fontWeight: 500 }}>
            action medeor - Procurement
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          <NavItem
            icon={<Home size={15} />}
            label="Home"
            active={currentScreen === 'home'}
            onClick={() => onNavigate('home')}
          />
          <NavItem
            icon={<LayoutDashboard size={15} />}
            label="Trend Dashboard"
            active={currentScreen === 'dashboard'}
            onClick={() => onNavigate('dashboard')}
          />

          <NavGroup label="Request Workflow" />
          <NavItem
            icon={<FileText size={15} />}
            label="Import Request"
            active={currentScreen === 'ingestion'}
            onClick={() => onNavigate('ingestion')}
          />
          <NavItem
            icon={<ListChecks size={15} />}
            label="Review Items"
            active={currentScreen === 'review'}
            onClick={() => onNavigate('review')}
            indent
          />
          <NavItem
            icon={<GitMerge size={15} />}
            label="Smart Matching"
            active={currentScreen === 'matching'}
            onClick={() => onNavigate('matching')}
            indent
          />
          <NavItem
            icon={<ClipboardList size={15} />}
            label="Order Summary"
            active={currentScreen === 'summary'}
            onClick={() => onNavigate('summary')}
            indent
          />

          <NavGroup label="Management" />
          <NavItem icon={<Clock size={15} />} label="Request History" active={false} onClick={() => {}} />
          <NavItem icon={<Settings size={15} />} label="Settings" active={false} onClick={() => {}} />
          <NavItem icon={<HelpCircle size={15} />} label="Help & Support" active={false} onClick={() => {}} />
        </nav>

        <div className="p-3 border-t border-white/10">
          <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg hover:bg-white/10 cursor-pointer transition-colors">
            <div className="w-8 h-8 rounded-full bg-[#1B4E8A] flex items-center justify-center flex-shrink-0 border border-white/20">
              <User size={14} className="text-white" />
            </div>
            <div className="min-w-0">
              <div className="text-white truncate" style={{ fontSize: 13, fontWeight: 500 }}>
                Lea Fischer
              </div>
              <div className="text-white/50" style={{ fontSize: 11 }}>
                Procurement Manager
              </div>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="h-16 bg-white border-b border-gray-200 flex items-center px-6 justify-between flex-shrink-0 z-10">
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => onNavigate('home')}
              className="text-gray-400 text-sm hover:text-gray-700 transition-colors"
            >
              Allocura
            </button>
            {currentScreen !== 'home' && (
              <>
                {isWorkflow && (
                  <>
                    <ChevronRight size={13} className="text-gray-300" />
                    <span className="text-gray-400 text-sm">Request Workflow</span>
                  </>
                )}
                <ChevronRight size={13} className="text-gray-300" />
                <span className="text-gray-900 text-sm" style={{ fontWeight: 500 }}>
                  {SCREEN_LABELS[currentScreen]}
                </span>
              </>
            )}
          </div>

          <div
            className="px-3 py-1 bg-blue-50 border border-blue-100 rounded-full text-xs text-blue-700"
            style={{ fontWeight: 500 }}
          >
            action medeor
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

function NavGroup({ label }: { label: string }) {
  return (
    <div className="pt-4 pb-1">
      <div
        className="text-white/40 px-3 pb-1"
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
    </div>
  );
}

function NavItem({
  icon,
  label,
  active,
  onClick,
  indent,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  indent?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 rounded-lg transition-colors text-left ${
        indent ? 'pl-7 pr-3 py-1.5' : 'px-3 py-2'
      } ${active ? 'bg-white/15 text-white' : 'text-white/55 hover:text-white/85 hover:bg-white/8'}`}
      style={{ fontSize: 13 }}
    >
      <span className={active ? 'text-white' : 'text-white/55'}>{icon}</span>
      {label}
      {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#0E9E8F]" />}
    </button>
  );
}

