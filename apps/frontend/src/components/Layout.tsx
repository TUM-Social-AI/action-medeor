import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Activity,
  ChevronRight,
  Clock,
  FileText,
  HelpCircle,
  Home,
  LayoutDashboard,
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
  const [profileOpen, setProfileOpen] = useState(false);
  const [savingAvatar, setSavingAvatar] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const firstAvatarRef = useRef<HTMLButtonElement>(null);

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
    <div className="flex h-screen bg-[#F0F2F7] overflow-hidden">
      <aside className="relative z-20 w-56 bg-[#0F2044] flex flex-col flex-shrink-0 shadow-xl">
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

        <nav aria-label="Main navigation" className="flex-1 p-3 space-y-0.5 overflow-y-auto">
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

          <NavItem
            icon={<FileText size={15} />}
            label="New Request"
            active={isWorkflow}
            disabled={isWorkflow}
            onClick={() => onNavigate('ingestion')}
          />

          <NavGroup label="Management" />
          <NavItem icon={<Clock size={15} />} label="Request History" active={currentScreen === 'history'} onClick={() => onNavigate('history')} />
          <NavItem icon={<Settings size={15} />} label="Settings" active={currentScreen === 'settings'} onClick={() => onNavigate('settings')} />
          <NavItem icon={<HelpCircle size={15} />} label="Help & Support" active={currentScreen === 'help'} onClick={() => onNavigate('help')} />
        </nav>

        <div ref={profileRef} className="relative p-3 border-t border-white/10">
          {profileOpen && <div
            id="avatar-picker"
            role="dialog"
            aria-label="Choose your avatar"
            className="absolute bottom-full left-3 mb-3 w-72 rounded-xl border border-gray-200 bg-white p-4 shadow-xl"
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
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-white"
          >
            <div className="w-8 h-8 rounded-full bg-[#1B4E8A] flex items-center justify-center flex-shrink-0 border border-white/20">
              <img src={avatarUrl(avatarId)} alt="" className="w-full h-full rounded-full object-cover" />
            </div>
            <div className="min-w-0">
              <div className="text-white truncate" style={{ fontSize: 13, fontWeight: 500 }}>
                {displayName}
              </div>
              <div className="text-white/50" style={{ fontSize: 11 }}>
                action medeor
              </div>
            </div>
          </button>
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
  disabled = false,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-current={active && !disabled ? 'page' : undefined}
      className={`w-full flex items-center gap-2.5 rounded-lg transition-colors text-left px-3 py-2 focus-visible:outline-2 focus-visible:outline-white ${active ? 'bg-white/15 text-white' : 'text-white/55 hover:text-white/85 hover:bg-white/8'}`}
      style={{ fontSize: 13 }}
    >
      <span className={active ? 'text-white' : 'text-white/55'}>{icon}</span>
      {label}
      {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[#0E9E8F]" />}
    </button>
  );
}

