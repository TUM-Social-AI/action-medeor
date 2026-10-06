import { useEffect, useState } from 'react';
import { getExtractionPreferences, saveExtractionPreferences, type ExtractionMode } from '../api/identity';

export function SettingsScreen() {
  const [mode, setMode] = useState<ExtractionMode>('balanced');
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    getExtractionPreferences().then(value => { if (active) setMode(value.mode); })
      .catch(() => { if (active) setMessage('Unable to load extraction preferences.'); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  const save = async (choice: ExtractionMode) => {
    setBusy(true);
    try {
      const result = await saveExtractionPreferences(choice);
      setMode(result.mode);
      setMessage('Saved. This applies to future uploads.');
    } catch {
      setMessage('Unable to save extraction preferences.');
    } finally { setBusy(false); }
  };
  return <div className="p-6 max-w-6xl mx-auto">
    <div className="mb-6">
      <h1 className="text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500 mt-1">Information about your procurement workspace.</p>
    </div>
    <section aria-labelledby="extraction-preferences" className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
      <h2 id="extraction-preferences" className="text-gray-900 mb-2">AI assistance for imports</h2>
      <p className="text-sm text-gray-500 mb-4">Copy source values first, then choose how much AI checks. Your final confirmation is always required.</p>
      {([
        ['balanced', 'Balanced — default', 'Column assistance plus a batched AI review. Clear gaps are filled and checked rows need no individual verification.'],
        ['basic', 'Basic', 'Use AI only for unclear columns and free-text extraction. Verify extracted rows yourself.'],
      ] as const).map(([value, label, description]) => <label key={value} className="flex gap-3 mb-4 cursor-pointer">
        <input type="radio" name="extraction-mode" value={value} checked={mode === value} disabled={busy} onChange={() => void save(value)} className="mt-1" />
        <span><span className="text-sm font-medium text-gray-900">{label}</span><span className="block text-sm text-gray-500">{description}</span></span>
      </label>)}
      {message && <p role="status" className="text-sm text-gray-600">{message}</p>}
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
