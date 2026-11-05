import { useRef, useState } from 'react';
import { translateRequestItem, type SavedMatchLine } from '../api/workflow';

export function RequestedItemName({ requestId, line }: { requestId: string; line: SavedMatchLine }) {
  const [translation, setTranslation] = useState(line.translatedName ?? null);
  const [showTranslation, setShowTranslation] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const cached = translation ?? line.translatedName;

  async function toggle() {
    if (busy.current) return;
    if (showTranslation) { setShowTranslation(false); return; }
    if (cached) { setShowTranslation(true); return; }
    busy.current = true;
    setLoading(true);
    setError(null);
    try {
      const result = await translateRequestItem(requestId, line.itemId);
      setTranslation(result.translation);
      setShowTranslation(true);
    } catch {
      setError('Translation unavailable. Please try again.');
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }

  return <span>
    <span lang={showTranslation ? 'de' : line.originalLanguage ?? undefined} className="text-sm text-gray-900 font-bold">{showTranslation ? cached : line.name}</span>
    <button type="button" onClick={() => void toggle()} disabled={loading} aria-busy={loading}
      className="ml-2 text-xs text-[#1B4E8A] underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1B4E8A] disabled:cursor-wait disabled:opacity-50">
      {loading ? 'Translating…' : showTranslation ? 'Back to original' : cached ? 'See translation' : 'Generate translation'}
    </button>
    {loading && <span role="status" className="sr-only">Translating into German…</span>}
    {error && <span role="alert" className="ml-2 text-xs text-red-700">{error}</span>}
  </span>;
}
