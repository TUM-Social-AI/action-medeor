import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  FileText,
  PenLine,
  Upload,
  X,
} from 'lucide-react';
import { listRequests, type SavedRequest } from '../api/workflow';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type IngestionScreenProps = {
  onContinue: (file: File) => void;
  error?: string | null;
  onOpenRequest: (request: SavedRequest) => void;
  onStartManual: () => void;
  isStartingManual?: boolean;
};

function isValidFile(file: File) {
  return ['.pdf', '.xlsx', '.xls', '.docx', '.csv'].some(extension =>
    file.name.toLowerCase().endsWith(extension),
  );
}

export function IngestionScreen({ onContinue, error: workflowError, onOpenRequest, onStartManual, isStartingManual = false }: IngestionScreenProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [imports, setImports] = useState<SavedRequest[]>([]);
  const [isLoadingImports, setIsLoadingImports] = useState(true);
  const [importsError, setImportsError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let mounted = true;

    listRequests()
      .then(response => {
        if (mounted) {
          setImports(response);
          setImportsError(null);
        }
      })
      .catch(caught => {
        if (mounted) {
          setImportsError(caught instanceof Error ? caught.message : 'Unable to reach backend');
        }
      })
      .finally(() => {
        if (mounted) {
          setIsLoadingImports(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && isValidFile(file)) {
      setUploadedFile(file);
    }
  };

  const handleFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file && isValidFile(file)) {
      setUploadedFile(file);
    }
  };

  return (
    <div className="px-4 py-2 lg:px-5 max-w-6xl mx-auto">
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-1.5 mb-3">
        <WorkflowStepper currentStep="ingestion" />
      </div>

      <div className="flex flex-col lg:flex-row gap-4">
        <div className="flex-1 min-w-0">
          <div className="mb-3">
            <h1 className="text-gray-900 text-xl leading-7">Import Partner Request</h1>
            <p className="text-gray-500 text-xs leading-4 mt-0.5">
              Upload a medical supply request file received from a partner organization in a crisis
              region. Allocura will extract items automatically and prepare them for review.
            </p>
          </div>

          {workflowError && <div className="mb-4"><ErrorPanel message={workflowError} /></div>}

          <div
            onDragOver={event => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl px-6 py-7 flex flex-col items-center justify-center cursor-pointer transition-all select-none ${
              isDragging
                ? 'border-[#1B4E8A] bg-blue-50/60'
                : uploadedFile
                  ? 'border-[#0E9E8F] bg-teal-50/40'
                  : 'border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100/70'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.xlsx,.xls,.docx,.csv"
              className="hidden"
              onChange={handleFileInput}
            />

            {uploadedFile ? (
              <>
                <div className="w-12 h-12 rounded-full bg-[#0E9E8F]/15 flex items-center justify-center mb-3">
                  <CheckCircle2 size={26} className="text-[#0E9E8F]" />
                </div>
                <div className="text-gray-900 text-sm mb-1" style={{ fontWeight: 600 }}>
                  File ready for processing
                </div>
                <div className="text-gray-700 text-xs max-w-full truncate" title={uploadedFile.name} style={{ fontWeight: 500 }}>
                  {uploadedFile.name}
                </div>
                <div className="text-gray-400 text-xs mt-1">
                  {uploadedFile.size > 0 ? `${(uploadedFile.size / 1024).toFixed(1)} KB` : 'File selected'}
                </div>
                <button
                  onClick={event => {
                    event.stopPropagation();
                    setUploadedFile(null);
                  }}
                  className="mt-2 flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X size={12} /> Remove file
                </button>
              </>
            ) : (
              <>
                <div className="w-12 h-12 rounded-full bg-gray-200 flex items-center justify-center mb-3">
                  <Upload size={24} className="text-gray-400" />
                </div>
                <div className="text-gray-700 text-sm mb-1" style={{ fontWeight: 600 }}>
                  Drag and drop your request file here
                </div>
                <div className="text-gray-400 text-xs">or click to browse from your computer</div>
                <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-2 mt-3">
                  <div className="flex items-center gap-1.5 text-xs text-gray-400">
                    <div className="w-6 h-6 rounded-md bg-green-100 flex items-center justify-center">
                      <FileSpreadsheet size={12} className="text-green-600" />
                    </div>
                    Excel/CSV (.xlsx, .xls, .csv)
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-gray-400">
                    <div className="w-6 h-6 rounded-md bg-red-100 flex items-center justify-center">
                      <FileText size={12} className="text-red-500" />
                    </div>
                    PDF
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-gray-400">
                    <div className="w-6 h-6 rounded-md bg-blue-100 flex items-center justify-center">
                      <FileText size={12} className="text-blue-600" />
                    </div>
                    Word (.docx)
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="mt-2 flex items-center justify-end">
            <button
              onClick={() => uploadedFile && onContinue(uploadedFile)}
              disabled={!uploadedFile || isStartingManual}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all ${
                uploadedFile
                  ? 'bg-[#1B4E8A] text-white hover:bg-[#163d6d] shadow-sm cursor-pointer'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed'
              }`}
              style={{ fontWeight: 500 }}
            >
              Continue to Review
              <ArrowRight size={15} />
            </button>
          </div>

          <div className="mt-2 flex items-center gap-3">
            <div className="h-px flex-1 bg-gray-200" />
            <span className="text-xs text-gray-400 uppercase tracking-wider font-semibold">or</span>
            <div className="h-px flex-1 bg-gray-200" />
          </div>
          <button
            onClick={onStartManual}
            disabled={isStartingManual}
            className="mt-2 w-full flex items-center gap-3 p-2.5 rounded-xl border border-gray-200 bg-white hover:border-[#1B4E8A]/40 hover:bg-blue-50/30 transition-colors text-left group disabled:opacity-60 disabled:cursor-wait"
          >
            <div className="w-8 h-8 rounded-lg bg-[#1B4E8A]/10 flex items-center justify-center flex-shrink-0">
              <PenLine size={16} className="text-[#1B4E8A]" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-gray-900 font-semibold">{isStartingManual ? 'Creating request…' : 'Create request manually'}</div>
              <div className="text-xs text-gray-500 mt-0.5">
                No file? Enter items line by line — for phone, e-mail or verbal requests.
              </div>
            </div>
            <ArrowRight size={16} className="text-gray-400 group-hover:text-[#1B4E8A] transition-colors" />
          </button>
        </div>

        <div className="w-full lg:w-60 flex-shrink-0">
          <div className="bg-white rounded-xl border border-gray-200 p-3">
            <div className="flex items-center gap-2 mb-3">
              <Clock size={14} className="text-gray-400" />
              <h3 className="text-gray-900 text-sm" style={{ fontWeight: 600 }}>
                Recent Requests
              </h3>
            </div>
            {isLoadingImports && <LoadingPanel label="Loading imports" />}
            {importsError && <ErrorPanel message={importsError} />}
            {!isLoadingImports && !importsError && (
              <div className="space-y-2">
                {imports.slice(0, 5).map(item => (
                  <button
                    key={item.requestId}
                    onClick={() => onOpenRequest(item)}
                    className="block w-full text-left p-2 bg-gray-50 rounded-lg hover:bg-gray-100 border border-gray-100"
                  >
                    <div className="text-xs font-medium text-gray-900 truncate" title={item.sourceFile || 'Manual request'}>{item.sourceFile || 'Manual request'}</div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">{item.partner || item.requestId}</div>
                    <div className="text-xs text-gray-400 mt-0.5">{item.itemCount} items · {item.status.replace(/_/g, ' ')}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
