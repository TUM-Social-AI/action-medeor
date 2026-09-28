import { useState } from 'react';
import { AVATARS, avatarUrl, type AvatarId } from '../api/identity';

type Props = {
  avatarId: AvatarId;
  onAvatarChange: (avatarId: AvatarId) => Promise<void>;
};

export function SettingsScreen({ avatarId, onAvatarChange }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chooseAvatar = async (choice: AvatarId) => {
    if (saving || choice === avatarId) return;
    setSaving(true);
    setError(null);
    try {
      await onAvatarChange(choice);
    } catch {
      setError('Could not save your avatar. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return <div className="p-6 max-w-6xl mx-auto">
    <div className="mb-6">
      <h1 className="text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500 mt-1">Make your workspace feel like yours.</p>
    </div>
    <section aria-labelledby="avatar-settings" className="bg-white rounded-xl border border-gray-200 p-6 mb-5">
      <h2 id="avatar-settings" className="text-gray-900 mb-1">Your avatar</h2>
      <p className="text-sm text-gray-500 mb-5">Pick an animal for your profile.</p>
      <div className="flex flex-wrap gap-3">
        {AVATARS.map(avatar => <button
          key={avatar.id}
          type="button"
          aria-label={`Choose ${avatar.label} avatar`}
          aria-pressed={avatarId === avatar.id}
          disabled={saving}
          onClick={() => void chooseAvatar(avatar.id)}
          className={`rounded-xl p-2 border-2 transition-colors disabled:opacity-60 ${avatarId === avatar.id ? 'border-[#0E9E8F] bg-teal-50' : 'border-gray-200 hover:border-gray-400'}`}
        >
          <img src={avatarUrl(avatar.id)} alt="" className="w-16 h-16 rounded-full" />
          <span className="block text-xs text-gray-700 mt-1">{avatar.label}</span>
        </button>)}
      </div>
      {error && <p role="alert" className="text-sm text-red-700 mt-4">{error}</p>}
    </section>
    <section aria-labelledby="app-information" className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 id="app-information" className="text-gray-900 mb-4">App information</h2>
      <dl className="grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-x-6 gap-y-3 text-sm">
        <dt className="text-gray-500">Application</dt><dd className="text-gray-900">Allocura</dd>
        <dt className="text-gray-500">Workspace</dt><dd className="text-gray-900">action medeor — Procurement</dd>
        <dt className="text-gray-500">Purpose</dt><dd className="text-gray-900">Review partner requests and match requested supplies to catalog products.</dd>
        <dt className="text-gray-500">Supported imports</dt><dd className="text-gray-900">PDF, Excel (.xlsx, .xls), Word (.docx), and CSV</dd>
      </dl>
    </section>
  </div>;
}
