import { useEffect, useState } from 'react';
import { ArrowRight, Plus } from 'lucide-react';
import { listRequests, type SavedRequest } from '../api/workflow';
import { ErrorPanel, LoadingPanel } from './ScreenState';

type Props = {
  onCreateRequest: () => void;
  onOpenRequest: (request: SavedRequest) => void;
  history?: boolean;
  error?: string | null;
};

export function HomeScreen({ onCreateRequest, onOpenRequest, history, error }: Props) {
  const [requests, setRequests] = useState<SavedRequest[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    listRequests()
      .then(value => { if (active) setRequests(value); })
      .catch(caught => { if (active) setLoadError(String(caught)); });
    return () => { active = false; };
  }, [history]);
  return <div className="p-6 max-w-5xl mx-auto">
    <div className="flex justify-between items-center mb-6">
      <div>
        <h1 className="text-gray-900">{history ? 'Request History' : 'Requests'}</h1>
        <p className="text-sm text-gray-500">Create a request or reopen saved extraction and matching work.</p>
      </div>
      <button onClick={onCreateRequest} className="flex items-center gap-2 px-5 py-3 bg-[#1B4E8A] text-white rounded-xl">
        <Plus size={16} /> New Request
      </button>
    </div>
    {(error || loadError) && <div className="mb-4"><ErrorPanel message={error || loadError || ''} /></div>}
    {!requests && !loadError && <LoadingPanel label="Loading requests" />}
    {requests && <div className="bg-white border rounded-xl overflow-hidden">
      {requests.length === 0 && <p className="p-6 text-sm text-gray-500">No requests yet.</p>}
      {requests.map(request => <button key={request.requestId} onClick={() => onOpenRequest(request)}
        className="w-full border-b last:border-b-0 p-4 flex items-center justify-between text-left hover:bg-gray-50">
        <div>
          <div className="font-semibold text-[#1B4E8A]">{request.requestId}</div>
          <div className="text-sm text-gray-600">{request.sourceFile || 'No file uploaded'} · {request.partner || 'Partner not specified'}</div>
          <div className="text-xs text-gray-400">{request.itemCount} items · {request.createdAt}</div>
        </div>
        <span className="flex items-center gap-2 text-sm text-gray-600">{request.status.replace(/_/g, ' ')} <ArrowRight size={15} /></span>
      </button>)}
    </div>}
  </div>;
}
