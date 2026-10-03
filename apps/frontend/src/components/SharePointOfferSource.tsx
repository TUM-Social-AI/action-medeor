import { ExternalLink, FileText } from 'lucide-react';
import type { SourceReferenceV1 } from '../api/matching/contracts';

type CandidateType = 'catalog' | 'historical_offer' | 'procurement' | null;
type Variant = 'inline' | 'compact' | 'footer';
type Props = {
  provenance: SourceReferenceV1[];
  candidateType?: CandidateType;
  variant?: Variant;
  className?: string;
  muted?: boolean;
};

type SharePointDocument = { url: string; name: string; id: string };

export function sharePointDocuments(provenance: SourceReferenceV1[]): SharePointDocument[] {
  return provenance.flatMap(source => {
    if (source.source_type !== 'sharepoint' || !source.uri) return [];
    try {
      const url = new URL(source.uri);
      if (url.protocol !== 'https:' || !url.hostname.toLowerCase().endsWith('.sharepoint.com')) return [];
      const lastSegment = url.pathname.split('/').filter(Boolean).at(-1) ?? '';
      let name = lastSegment;
      try { name = decodeURIComponent(lastSegment); } catch { /* Keep the encoded name. */ }
      return [{ url: url.href, name: name || 'Offer document', id: source.document_id }];
    } catch {
      return [];
    }
  });
}

export function SharePointOfferSource({ provenance, candidateType, variant = 'inline', className = '', muted = false }: Props) {
  const sources = provenance.filter(source => source.source_type === 'sharepoint');
  if (!sources.length) return null;
  const documents = sharePointDocuments(provenance);
  const isOffer = candidateType === 'historical_offer';

  if (variant === 'footer') {
    const document = documents[0];
    const tone = muted ? 'border-gray-200 bg-gray-100 text-gray-500 hover:bg-gray-200/70' : 'border-violet-200 bg-violet-100 text-violet-900 hover:bg-violet-200/70';
    return document ? <a href={document.url} target="_blank" rel="noopener noreferrer"
      title={`Open ${document.name} in SharePoint`}
      className={'group flex items-center gap-2 border-t px-4 py-2 ' + tone + ' ' + className}>
      <FileText size={14} className={'shrink-0 ' + (muted ? 'text-gray-400' : 'text-violet-600')} />
      <span className="min-w-0 flex-1 truncate text-xs font-medium group-hover:underline">{document.name}</span>
      <span className={'flex shrink-0 items-center gap-1 text-[11px] font-semibold ' + (muted ? 'text-gray-500' : 'text-violet-700')}>SharePoint offer <ExternalLink size={11} /></span>
    </a> : <div className={'border-t px-4 py-2 text-xs font-semibold ' + tone + ' ' + className}>SharePoint offer</div>;
  }

  if (variant === 'compact') {
    return <span className={'inline-flex max-w-full flex-wrap items-center gap-1.5 text-xs text-violet-800 ' + className}>
      <FileText size={13} className="shrink-0 text-violet-600" />
      {documents[0] ? <a href={documents[0].url} target="_blank" rel="noopener noreferrer"
        title={`Open ${documents[0].name} in SharePoint`}
        className="inline-flex min-w-0 items-center gap-1 font-medium hover:underline">
        <span className="truncate">{documents[0].name}</span><ExternalLink size={11} className="shrink-0" />
      </a> : <span>SharePoint offer</span>}
    </span>;
  }

  return <div className={'text-xs ' + (isOffer ? 'text-violet-800 ' : 'text-[#1B4E8A] ') + className}>
    <span className="font-semibold">{isOffer ? 'Offer from SharePoint' : 'Related SharePoint offer'}</span>
    {documents.map((document, index) => <span key={document.id + ':' + index}>
      {' · '}<a href={document.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-violet-950">
        {documents.length > 1 ? `Open document ${index + 1}` : 'Open document'}
      </a>
    </span>)}
  </div>;
}
