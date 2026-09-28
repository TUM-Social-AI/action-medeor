import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Activity,
  ChevronRight,
  Clock,
  FileText,
  HelpCircle,
  Home,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
} from 'lucide-react';
import type { Screen } from '../api/types';
import { AVATARS, avatarUrl, type AvatarId } from '../api/identity';

type LayoutProps = {
  children: ReactNode;
  currentScreen: Screen;
  onNavigate: (screen: Screen) => void;
  displayName: string;
  avatarId: AvatarId;
  onAvatarChange: (avatarId: AvatarId) => Promise<void>;
};

const SCREEN_LABELS: Record<Screen, string> = {
  home: 'Home',
  history: 'Request History',
  dashboard: 'Trend Dashboard',
  ingestion: 'Import Request',
  review: 'Review Items',
  matching: 'Smart Matching',
  summary: 'Order Summary',
  settings: 'Settings',
  help: 'Help & Support',
};

const WORKFLOW_SCREENS: Screen[] = ['ingestion', 'review', 'matching', 'summary'];

export function Layout({ children, currentScreen, onNavigate, displayName, avatarId, onAvatarChange }: LayoutProps) {
  const isWorkflow = WORKFLOW_SCREENS.includes(currentScreen);
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 1199px)').matches);
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 639px)').matches);
  const [sidebarExpanded, setSidebarExpanded] = useState(() => !window.matchMedia('(max-width: 1199px)').matches);
  const [profileOpen, setProfileOpen] = useState(false);
  const [savingAvatar, setSavingAvatar] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const firstAvatarRef = useRef<HTMLButtonElement>(null);
  const expandSidebarRef = useRef<HTMLButtonElement>(null);
  const collapseSidebarRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1199px)');
    const phoneQuery = window.matchMedia('(max-width: 639px)');
    const updatePhone = () => setPhone(phoneQuery.matches);
    const update = () => {
      setCompact(query.matches);
      setSidebarExpanded(!query.matches);
      setProfileOpen(false);
    };
    query.addEventListener('change', update);
    phoneQuery.addEventListener('change', updatePhone);
    return () => {
      query.removeEventListener('change', update);
      phoneQuery.removeEventListener('change', updatePhone);
    };
  }, []);

  useEffect(() => {
    if (!compact || !sidebarExpanded) return;
    collapseSidebarRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSidebarExpanded(false);
        expandSidebarRef.current?.focus();
      }
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [compact, sidebarExpanded]);

  const navigate = (screen: Screen) => {
    onNavigate(screen);
    if (compact) setSidebarExpanded(false);
    setProfileOpen(false);
  };

  useEffect(() => {
    if (!profileOpen) return;
    firstAvatarRef.current?.focus();
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!profileRef.current?.contains(event.target as Node)) setProfileOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setProfileOpen(false);
        profileButtonRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [profileOpen]);

  const chooseAvatar = async (choice: AvatarId) => {
    if (savingAvatar || choice === avatarId) return;
    setSavingAvatar(true);
    setAvatarError(null);
    try {
      await onAvatarChange(choice);
      setProfileOpen(false);
      profileButtonRef.current?.focus();
    } catch {
      setAvatarError('Could not save your avatar. Please try again.');
    } finally {
      setSavingAvatar(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#F0F2F7] overflow-hidden" style={{ '--sidebar-width': phone ? '0rem' : compact || !sidebarExpanded ? '4rem' : '14rem' } as CSSProperties}>
      {compact && sidebarExpanded && <button type="button" aria-label="Close sidebar" onClick={() => setSidebarExpanded(false)} className="fixed inset-0 z-40 bg-black/30" />}
      <aside id="app-sidebar" className={'z-50 bg-[#0F2044] flex flex-col flex-shrink-0 shadow-xl transition-[width] duration-200 ' + (sidebarExpanded ? 'w-56 ' : 'w-16 ') + (compact && sidebarExpanded ? 'fixed inset-y-0 left-0' : phone ? 'hidden' : 'relative')}>
        <div className={'h-16 flex items-center border-b border-white/10 ' + (sidebarExpanded ? 'justify-between px-4' : 'justify-center')}>
          <button onClick={() => navigate('home')} aria-label="Go to home" title="Home" className="flex items-center gap-2.5 hover:opacity-80 transition-opacity min-w-0">
            <div className="w-8 h-8 rounded-lg bg-[#0E9E8F] flex items-center justify-center shadow-sm flex-shrink-0"><Activity size={16} className="text-white" /></div>
            {sidebarExpanded && <span className="text-white font-bold text-lg truncate">Allocura</span>}
          </button>
          {sidebarExpanded && <button ref={collapseSidebarRef} type="button" onClick={() => setSidebarExpanded(false)} aria-label="Collapse sidebar" aria-controls="app-sidebar" aria-expanded={true} title="Collapse sidebar" className="p-1.5 rounded-lg text-white/70 hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-white"><PanelLeftClose size={18} /></button>}
        </div>

        {sidebarExpanded && <div className="px-5 py-2.5 border-b border-white/10"><div className="text-white/40 text-[11px] font-medium">action medeor - Procurement</div></div>}

        <nav aria-label="Main navigation" className={'flex-1 space-y-0.5 overflow-y-auto ' + (sidebarExpanded ? 'p-3' : 'p-2')}>
          <NavItem
            icon={<Home size={15} />}
            label="Home"
            active={currentScreen === 'home'}
            collapsed={!sidebarExpanded}
            onClick={() => navigate('home')}
          />
          <NavItem
            icon={<LayoutDashboard size={15} />}
            label="Trend Dashboard"
            active={currentScreen === 'dashboard'}
            collapsed={!sidebarExpanded}
            onClick={() => navigate('dashboard')}
          />

          <NavItem
            icon={<FileText size={15} />}
            label="New Request"
            active={isWorkflow}
            disabled={isWorkflow}
            collapsed={!sidebarExpanded}
            onClick={() => navigate('ingestion')}
          />

          <NavGroup label="Management" collapsed={!sidebarExpanded} />
          <NavItem icon={<Clock size={15} />} label="Request History" active={currentScreen === 'history'} collapsed={!sidebarExpanded} onClick={() => navigate('history')} />
          <NavItem icon={<Settings size={15} />} label="Settings" active={currentScreen === 'settings'} collapsed={!sidebarExpanded} onClick={() => navigate('settings')} />
          <NavItem icon={<HelpCircle size={15} />} label="Help & Support" active={currentScreen === 'help'} collapsed={!sidebarExpanded} onClick={() => navigate('help')} />
        </nav>

        <div ref={profileRef} className={'relative border-t border-white/10 ' + (sidebarExpanded ? 'p-3' : 'p-2')}>
          {profileOpen && <div
            id="avatar-picker"
            role="dialog"
            aria-label="Choose your avatar"
            className={'absolute w-72 rounded-xl border border-gray-200 bg-white p-4 shadow-xl ' + (sidebarExpanded ? 'bottom-full left-3 mb-3' : 'bottom-0 left-full ml-2')}
          >
            <h2 className="text-sm font-semibold text-gray-900">Choose your avatar</h2>
            <p className="mt-1 text-xs text-gray-500">Pick an animal for your profile.</p>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {AVATARS.map((avatar, index) => <button
                key={avatar.id}
                ref={index === 0 ? firstAvatarRef : undefined}
                type="button"
                aria-label={`Choose ${avatar.label} avatar`}
                aria-pressed={avatarId === avatar.id}
                disabled={savingAvatar}
                onClick={() => void chooseAvatar(avatar.id)}
                className={`rounded-lg border-2 p-1.5 text-center transition-colors disabled:opacity-60 ${avatarId === avatar.id ? 'border-[#0E9E8F] bg-teal-50' : 'border-gray-200 hover:border-gray-400'}`}
              >
                <img src={avatarUrl(avatar.id)} alt="" className="mx-auto h-12 w-12 rounded-full" />
                <span className="mt-1 block text-xs text-gray-700">{avatar.label}</span>
              </button>)}
            </div>
            {avatarError && <p role="alert" className="mt-3 text-xs text-red-700">{avatarError}</p>}
          </div>}
          <button
            ref={profileButtonRef}
            type="button"
            aria-label={`Profile: ${displayName}. Choose avatar`}
            aria-expanded={profileOpen}
            aria-controls="avatar-picker"
            onClick={() => { setAvatarError(null); setProfileOpen(open => !open); }}
            className={'flex w-full items-center gap-2.5 rounded-lg py-2 text-left transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-white ' + (sidebarExpanded ? 'px-2.5' : 'justify-center px-0')}
          >
            <div className="w-8 h-8 rounded-full bg-[#1B4E8A] flex items-center justify-center flex-shrink-0 border border-white/20">
              <img src={avatarUrl(avatarId)} alt="" className="w-full h-full rounded-full object-cover" />
            </div>
            {sidebarExpanded && <div className="min-w-0">
              <div className="text-white truncate" style={{ fontSize: 13, fontWeight: 500 }}>{displayName}</div>
              <div className="text-white/50" style={{ fontSize: 11 }}>action medeor</div>
            </div>}
          </button>
        </div>
      </aside>
      {compact && sidebarExpanded && !phone && <div className="w-16 flex-shrink-0" aria-hidden="true" />}

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="h-16 bg-white border-b border-gray-200 flex items-center px-3 sm:px-6 justify-between gap-3 flex-shrink-0 z-10">
          <div className="flex items-center gap-1.5 min-w-0">
            {!sidebarExpanded && <button ref={expandSidebarRef} type="button" onClick={() => setSidebarExpanded(true)} aria-label="Expand sidebar" aria-controls="app-sidebar" aria-expanded={false} title="Expand sidebar" className="mr-2 p-1.5 rounded-lg text-gray-600 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-[#1B4E8A]"><PanelLeftOpen size={19} /></button>}
            <button
              onClick={() => navigate('home')}
              className="text-gray-400 text-sm hover:text-gray-700 transition-colors hidden sm:block"
            >
              Allocura
            </button>
            {currentScreen !== 'home' && (
              <>
                {isWorkflow && (
                  <>
                    <ChevronRight size={13} className="text-gray-300" />
                    <span className="text-gray-400 text-sm hidden md:inline">Request Workflow</span>
                  </>
                )}
                <ChevronRight size={13} className="text-gray-300" />
                <span className="text-gray-900 text-sm truncate" style={{ fontWeight: 500 }}>
                  {SCREEN_LABELS[currentScreen]}
                </span>
              </>
            )}
          </div>

          <div
            className="hidden sm:block px-3 py-1 bg-blue-50 border border-blue-100 rounded-full text-xs text-blue-700 flex-shrink-0"
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

function NavGroup({ label, collapsed }: { label: string; collapsed: boolean }) {
  return (
    <div className={collapsed ? 'my-3 border-t border-white/10' : 'pt-4 pb-1'}>
      {!collapsed && <div
        className="text-white/40 px-3 pb-1"
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>}
    </div>
  );
}

function NavItem({
  icon,
  label,
  active,
  collapsed,
  disabled = false,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  collapsed: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-current={active && !disabled ? 'page' : undefined}
      aria-label={collapsed ? label : undefined}
      title={collapsed ? label : undefined}
      className={`w-full flex items-center gap-2.5 rounded-lg transition-colors text-left focus-visible:outline-2 focus-visible:outline-white ${collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2'} ${active ? 'bg-white/15 text-white' : 'text-white/55 hover:text-white/85 hover:bg-white/8'}`}
      style={{ fontSize: 13 }}
    >
      <span className={active ? 'text-white' : 'text-white/55'}>{icon}</span>
      {!collapsed && label}
      {!collapsed && active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#0E9E8F]" />}
    </button>
  );
}

