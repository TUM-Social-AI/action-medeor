import { useEffect, useRef, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';
import { getImportProgress } from '../api/client';
import type { LoadingType, WorkflowStep } from '../api/types';
import {
  extractionPercent,
  extractionStages,
  extractionSteps,
  type ExtractionMode,
  type ExtractionStage,
} from '../features/loading/progress';
import { WorkflowStepper } from './WorkflowStepper';

type ProgressConfig = {
  title: string;
  subtitle: string;
  steps: readonly string[];
  accentColor: string;
  iconBg: string;
};

const CONFIG: Record<LoadingType, Omit<ProgressConfig, 'steps'> & { step: WorkflowStep }> = {
  extracting: {
    step: 'review',
    title: 'Extracting Items from Document',
    subtitle: 'Allocura is parsing your upload and identifying medical items.',
    accentColor: '#1B4E8A',
    iconBg: 'bg-blue-50',
  },
  matching: {
    step: 'matching',
    title: 'Running Smart Matching',
    subtitle: 'Comparing your verified items against the ERP catalogue.',
    accentColor: '#0E9E8F',
    iconBg: 'bg-teal-50',
  },
};

const MATCHING_STEPS = ['Queueing items for matching', 'Matching items against the ERP catalogue', 'Opening results'];

export function ProcessingProgress({
  title, subtitle, steps, completedSteps, accentColor, iconBg, titleId, subtitleId, percent, detail,
}: ProgressConfig & {
  completedSteps: number; titleId?: string; subtitleId?: string;
  /** Real progress (0-100); defaults to the share of completed steps. */
  percent?: number;
  detail?: string;
}) {
  const progress = percent ?? (completedSteps / steps.length) * 100;

  return <>
    <div className={`w-16 h-16 rounded-2xl ${iconBg} flex items-center justify-center mx-auto mb-6`}>
      <Loader2 size={28} className="animate-spin motion-reduce:animate-none" style={{ color: accentColor }} />
    </div>

    <div className="text-center mb-7">
      <h2 id={titleId} className="text-gray-900 mb-1.5">{title}</h2>
      <p id={subtitleId} className="text-gray-500 text-sm">{subtitle}</p>
      {detail && <p className="text-gray-700 text-sm mt-2" style={{ fontWeight: 500 }} aria-live="polite">{detail}</p>}
    </div>

    <div
      className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-6"
      role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}
    >
      <div
        className="h-full rounded-full transition-all duration-500 ease-out motion-reduce:transition-none"
        style={{ width: `${progress}%`, backgroundColor: accentColor }}
      />
    </div>

    <div className="space-y-3">
      {steps.map((label, index) => {
        const done = index < completedSteps;
        const active = index === completedSteps;
        return <div
          key={label}
          className={`flex items-center gap-3 transition-colors duration-300 motion-reduce:transition-none ${
            done ? 'text-gray-400' : active ? 'text-gray-800' : 'text-gray-300'
          }`}
          style={{ fontSize: 13 }}
        >
          <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 transition-all motion-reduce:transition-none ${
            done ? 'bg-green-100' : active ? iconBg : 'bg-gray-100'
          }`}>
            {done ? <Check size={11} className="text-green-600" /> : <div
              className={`w-2 h-2 rounded-full ${active ? 'animate-pulse motion-reduce:animate-none' : ''}`}
              style={{ backgroundColor: active ? accentColor : '#D1D5DB' }}
            />}
          </div>
          {label}
        </div>;
      })}
    </div>
  </>;
}

const POLL_MS = 750;
const TICK_MS = 200;

export function ProcessingScreen({
  type, progressToken, matching,
}: {
  type: LoadingType;
  /** Extraction: token sent with the upload; its stage is polled while the upload runs. */
  progressToken?: string | null;
  /** Matching: real processed/total from the matching worker. */
  matching?: { processed: number; total: number } | null;
}) {
  const config = CONFIG[type];
  const [stage, setStage] = useState<ExtractionStage>('uploading');
  const stageRef = useRef<ExtractionStage>('uploading');
  const [mode, setMode] = useState<ExtractionMode>('balanced');
  const [items, setItems] = useState<number | null>(null);
  const [stageStartedAt, setStageStartedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (type !== 'extracting') return;
    const tick = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(tick);
  }, [type]);

  useEffect(() => {
    if (type !== 'extracting' || !progressToken) return;
    let active = true;
    const poll = () => getImportProgress(progressToken)
      .then(progress => {
        if (!active) return;
        setMode(progress.mode);
        if (progress.items !== null) setItems(progress.items);
        if (stageRef.current !== progress.stage) {
          stageRef.current = progress.stage;
          setStage(progress.stage);
          setStageStartedAt(Date.now());
        }
      })
      .catch(() => {}); // not started yet (or already finished): keep the current estimate
    void poll();
    const timer = window.setInterval(poll, POLL_MS);
    return () => { active = false; window.clearInterval(timer); };
  }, [type, progressToken]);

  let steps: string[];
  let completedSteps: number;
  let percent: number;
  let detail: string | undefined;
  if (type === 'extracting') {
    steps = extractionSteps(mode);
    completedSteps = Math.max(0, extractionStages(mode).indexOf(stage));
    percent = extractionPercent(stage, mode, now - stageStartedAt);
    detail = items !== null ? `${items} ${items === 1 ? 'item' : 'items'} found` : undefined;
  } else {
    const total = matching?.total ?? 0;
    const processed = matching?.processed ?? 0;
    steps = MATCHING_STEPS;
    completedSteps = total ? 1 : 0;
    percent = total ? (processed / total) * 100 : 0;
    detail = total ? `${processed} of ${total} items matched` : undefined;
  }

  return <div className="h-full flex flex-col items-center justify-center p-8 bg-[#F0F2F7]">
    <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 w-full max-w-2xl mb-8">
      <WorkflowStepper currentStep={config.step} />
    </div>
    <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-10 w-full max-w-md">
      <ProcessingProgress
        {...config}
        steps={steps}
        completedSteps={completedSteps}
        percent={percent}
        detail={detail}
      />
    </div>
  </div>;
}
