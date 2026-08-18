import { AlertCircle, Loader2 } from 'lucide-react';

export function LoadingPanel({ label = 'Loading data' }: { label?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-8 flex items-center justify-center gap-3 text-gray-500">
      <Loader2 size={18} className="animate-spin text-[#1B4E8A]" />
      <span className="text-sm" style={{ fontWeight: 600 }}>
        {label}
      </span>
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="bg-red-50 rounded-xl border border-red-200 p-5 flex items-start gap-3 text-red-800">
      <AlertCircle size={18} className="flex-shrink-0 mt-0.5 text-red-500" />
      <div>
        <div className="text-sm" style={{ fontWeight: 700 }}>
          Unable to load backend data
        </div>
        <div className="text-xs mt-1 leading-relaxed">{message}</div>
      </div>
    </div>
  );
}

