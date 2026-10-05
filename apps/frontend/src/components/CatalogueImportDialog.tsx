import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Upload, X } from 'lucide-react';
import {
  getCatalogueEmbeddingStatus, importCatalogue,
  type CatalogEmbeddingStatus, type CatalogImportResult,
} from '../api/catalogue';
import { catalogImportError, validateCatalogFiles } from '../features/catalogue/import';

export function CatalogueImportDialog({ onClose, onUpdated }: {
  onClose: () => void; onUpdated: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const articleInput = useRef<HTMLInputElement>(null);
  const translationInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(false);
  const submitting = useRef(false);
  const updated = useRef(onUpdated);
  updated.current = onUpdated;
  const [articles, setArticles] = useState<File | null>(null);
  const [translations, setTranslations] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CatalogImportResult | null>(null);
  const [progress, setProgress] = useState<CatalogEmbeddingStatus | null>(null);
  const [progressError, setProgressError] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    dialog.current?.showModal();
    return () => { mounted.current = false; dialog.current?.close(); };
  }, []);

  useEffect(() => {
    if (!result) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let completed: number | null = null;
    async function poll() {
      try {
        const status = await getCatalogueEmbeddingStatus(result!.import_id, controller.signal);
        if (controller.signal.aborted) return;
        setProgress(status);
        setProgressError(null);
        if (completed !== status.completed) updated.current();
        completed = status.completed;
        if (!status.configuration_error && status.pending === 0 && status.running === 0) return;
      } catch (caught) {
        if (controller.signal.aborted) return;
        setProgressError(catalogImportError(caught));
      }
      timer = setTimeout(() => { void poll(); }, 5000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [result]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    const validation = validateCatalogFiles(articles, translations);
    if (validation) { setError(validation); return; }
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      const imported = await importCatalogue(articles!, translations!);
      if (!mounted.current) return;
      setResult(imported);
      updated.current();
    } catch (caught) {
      if (mounted.current) setError(catalogImportError(caught));
    } finally {
      submitting.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <dialog ref={dialog} aria-labelledby="catalog-import-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
    className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl border-0 bg-white p-6 text-gray-900 shadow-xl backdrop:bg-black/40">
    <div className="mb-4 flex items-start justify-between gap-3">
      <h2 id="catalog-import-title" className="text-lg font-semibold">Update ERP catalogue</h2>
      <button type="button" disabled={busy} onClick={onClose} aria-label="Close ERP upload" className="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-40"><X size={18} /></button>
    </div>
    {result ? <div className="space-y-4 text-sm">
      <div role="status" className="rounded-lg bg-green-50 p-3 text-green-800">
        {result.idempotent_replay ? 'These files were already imported. No duplicate update was made.' : 'ERP catalogue and inventory updated.'}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        {([
          ['New articles', result.inserted_items], ['Text updates', result.text_updated_items],
          ['Metadata updates', result.metadata_updated_items], ['Unchanged articles', result.unchanged_items],
          ['Inventory refreshed', result.inventory_refreshed_items], ['Missing articles', result.missing_items],
          ['Reactivated articles', result.reactivated_items], ['Embedding jobs queued', result.embedding_jobs_created],
        ] as const).map(([label, count]) => <div key={label}><dt className="text-gray-500">{label}</dt><dd className="font-semibold">{count.toLocaleString()}</dd></div>)}
      </dl>
      {result.warnings.length > 0 && <div className="max-h-32 overflow-y-auto rounded-lg bg-amber-50 p-3 text-amber-900"><p className="font-semibold">Import warnings</p><ul className="mt-1 list-disc pl-5">{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
      <div aria-live="polite" className="rounded-lg bg-gray-50 p-3">
        <p className="font-semibold">Article embeddings</p>
        {progress ? <>
          <p className="mt-1">{progress.completed} ready · {progress.pending} pending · {progress.running} running · {progress.failed} failed</p>
          {progress.configuration_error && <p className="mt-2 text-amber-800">{progress.configuration_error} The catalogue update is saved.</p>}
          {!progress.configuration_error && progress.failed > 0 && <p className="mt-2 text-amber-800">Some embeddings failed. The catalogue update is saved; these articles may not appear in semantic search until processing succeeds.</p>}
          {!progress.configuration_error && progress.pending === 0 && progress.running === 0 && progress.failed === 0 && <p className="mt-2 text-green-700">Embedding processing complete.</p>}
        </> : <p className="mt-1">Checking embedding status…</p>}
        {progressError && <p className="mt-2 text-amber-800">Could not check embedding progress: {progressError}. The catalogue update is saved. Retrying…</p>}
        <p className="mt-2 text-xs text-gray-500">You can close this window. Queued processing runs in the background when embeddings are configured.</p>
      </div>
      <button type="button" onClick={onClose} className="w-full rounded-lg bg-[#1B4E8A] px-4 py-2 font-semibold text-white">Done</button>
    </div> : <form onSubmit={event => { void submit(event); }} className="space-y-4 text-sm">
      <p className="text-gray-600">Choose the complete current ERP exports. Inventory is refreshed for every article; new articles and changed product text get updated embeddings.</p>
      <div>
        <label htmlFor="erp-article-data" className="block font-semibold">Article data <span className="font-normal text-gray-500">(Artikeldaten.csv)</span></label>
        <input ref={articleInput} id="erp-article-data" type="file" accept=".csv,text/csv" disabled={busy} tabIndex={-1} onChange={event => setArticles(event.target.files?.[0] ?? null)} className="sr-only" />
        <div className="mt-1 flex min-w-0 items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 p-2">
          <button type="button" disabled={busy} onClick={() => articleInput.current?.click()} aria-label="Choose article data CSV" className="shrink-0 rounded-md border border-[#1B4E8A] bg-white px-3 py-2 font-semibold text-[#1B4E8A] shadow-sm hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1B4E8A] disabled:cursor-not-allowed disabled:opacity-50">Choose file</button>
          <span title={articles?.name} aria-live="polite" className="min-w-0 truncate text-gray-600">{articles?.name ?? 'No file selected'}</span>
        </div>
      </div>
      <div>
        <label htmlFor="erp-article-translations" className="block font-semibold">Article translations <span className="font-normal text-gray-500">(Artikeluebersetzungen.csv)</span></label>
        <input ref={translationInput} id="erp-article-translations" type="file" accept=".csv,text/csv" disabled={busy} tabIndex={-1} onChange={event => setTranslations(event.target.files?.[0] ?? null)} className="sr-only" />
        <div className="mt-1 flex min-w-0 items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 p-2">
          <button type="button" disabled={busy} onClick={() => translationInput.current?.click()} aria-label="Choose article translations CSV" className="shrink-0 rounded-md border border-[#1B4E8A] bg-white px-3 py-2 font-semibold text-[#1B4E8A] shadow-sm hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1B4E8A] disabled:cursor-not-allowed disabled:opacity-50">Choose file</button>
          <span title={translations?.name} aria-live="polite" className="min-w-0 truncate text-gray-600">{translations?.name ?? 'No file selected'}</span>
        </div>
      </div>
      <p className="text-xs text-gray-500">UTF-8 CSV files with semicolon separators, up to 25 MB each. The article data export must include the ERP columns Gesperrt, Verkauf gesperrt, and Einkauf gesperrt.</p>
      {error && <p role="alert" className="whitespace-pre-wrap rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
      <button type="submit" disabled={busy || !articles || !translations} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#1B4E8A] px-4 py-2 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"><Upload size={16} />{busy ? 'Uploading and updating…' : 'Upload and update'}</button>
    </form>}
  </dialog>;
}
