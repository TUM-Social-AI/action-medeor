import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  FileText,
  Info,
  Upload,
  X,
} from 'lucide-react';
import { getRecentImports } from '../api/client';
import type { RecentImport } from '../api/types';
import { ErrorPanel, LoadingPanel } from './ScreenState';
import { WorkflowStepper } from './WorkflowStepper';

type IngestionScreenProps = {
  onContinue: (file: File) => void;
  error?: string | null;
};

function isValidFile(file: File) {
  return ['.pdf', '.xlsx', '.xls'].some(extension => file.name.toLowerCase().endsWith(extension));
}

export function IngestionScreen({ onContinue, error: workflowError }: IngestionScreenProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [imports, setImports] = useState<RecentImport[]>([]);
  const [isLoadingImports, setIsLoadingImports] = useState(true);
  const [importsError, setImportsError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let mounted = true;

    getRecentImports()
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
    <div className="p-6 max-w-6xl mx-auto">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 mb-6">
        <WorkflowStepper currentStep="ingestion" />
      </div>

      <div className="flex gap-6">
        <div className="flex-1 min-w-0">
          <div className="mb-5">
            <h1 className="text-gray-900">Import Partner Request</h1>
            <p className="text-gray-500 text-sm mt-1">
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
            className={`relative border-2 border-dashed rounded-xl p-14 flex flex-col items-center justify-center cursor-pointer transition-all select-none ${
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
              accept=".pdf,.xlsx,.xls"
              className="hidden"
              onChange={handleFileInput}
            />

            {uploadedFile ? (
              <>
                <div className="w-16 h-16 rounded-full bg-[#0E9E8F]/15 flex items-center justify-center mb-4">
                  <CheckCircle2 size={30} className="text-[#0E9E8F]" />
                </div>
                <div className="text-gray-900 text-sm mb-1" style={{ fontWeight: 600 }}>
                  File ready for processing
                </div>
                <div className="text-gray-700 text-sm" style={{ fontWeight: 500 }}>
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
                  className="mt-3 flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X size={12} /> Remove file
                </button>
              </>
            ) : (
              <>
                <div className="w-16 h-16 rounded-full bg-gray-200 flex items-center justify-center mb-5">
                  <Upload size={26} className="text-gray-400" />
                </div>
                <div className="text-gray-700 text-sm mb-1" style={{ fontWeight: 600 }}>
                  Drag and drop your request file here
                </div>
                <div className="text-gray-400 text-sm">or click to browse from your computer</div>
                <div className="flex items-center gap-6 mt-7">
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <div className="w-7 h-7 rounded-md bg-green-100 flex items-center justify-center">
                      <FileSpreadsheet size={14} className="text-green-600" />
                    </div>
                    Excel (.xlsx, .xls)
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <div className="w-7 h-7 rounded-md bg-red-100 flex items-center justify-center">
                      <FileText size={14} className="text-red-500" />
                    </div>
                    PDF
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="mt-4 bg-blue-50 border border-blue-100 rounded-lg p-4 flex gap-3">
            <Info size={15} className="text-blue-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-blue-700 leading-relaxed">
              Partner request files should contain item names, quantities, and units. Allocura
              parses Excel sheets and PDF tables automatically. Supported languages: English,
              German, French, Arabic.
            </p>
          </div>

          <div className="mt-6 flex items-center justify-end">
            <button
              onClick={() => uploadedFile && onContinue(uploadedFile)}
              disabled={!uploadedFile}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm transition-all ${
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
        </div>

        <div className="flex-shrink-0" style={{ width: 272 }}>
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center gap-2 mb-4">
              <Clock size={14} className="text-gray-400" />
              <h3 className="text-gray-900 text-sm" style={{ fontWeight: 600 }}>
                Recent Imports
              </h3>
            </div>
            {isLoadingImports && <LoadingPanel label="Loading imports" />}
            {importsError && <ErrorPanel message={importsError} />}
            {!isLoadingImports && !importsError && (
              <div className="space-y-2.5">
                {imports.map(item => (
                  <div
                    key={item.id}
                    className="p-3 bg-gray-50 rounded-lg hover:bg-gray-100 cursor-pointer transition-colors border border-gray-100"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div
                          className="text-xs text-gray-900 truncate"
                          style={{ fontWeight: 500, maxWidth: 156 }}
                          title={item.fileName}
                        >
                          {item.fileName}
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">{item.partner}</div>
                      </div>
                      <div className="flex-shrink-0">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs ${
                            item.type === 'pdf' ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-700'
                          }`}
                          style={{ fontWeight: 600 }}
                        >
                          {item.type.toUpperCase()}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center justify-between mt-1.5">
                      <span className="text-xs text-gray-400">{item.date}</span>
                      <span className="text-xs text-gray-500">{item.items} items</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

