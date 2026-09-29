import { useEffect, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';
import type { LoadingType, WorkflowStep } from '../api/types';
import { WorkflowStepper } from './WorkflowStepper';

type ProgressConfig = {
  title: string;
  subtitle: string;
  steps: readonly string[];
  accentColor: string;
  iconBg: string;
};

const CONFIG: Record<LoadingType, ProgressConfig & { step: WorkflowStep; stepInterval: number }> = {
  extracting: {
    step: 'review',
    title: 'Extracting Items from Document',
    subtitle: 'Allocura is parsing your upload and identifying medical items.',
    steps: [
      'Parsing document structure',
      'Recognising medical item names',
      'Extracting quantities and units',
      'Scoring extraction confidence',
      'Finalising item list',
    ],
    accentColor: '#1B4E8A',
    iconBg: 'bg-blue-50',
    stepInterval: 520,
  },
  matching: {
    step: 'matching',
    title: 'Running Smart Matching',
    subtitle: 'Comparing your verified items against the ERP catalogue.',
    steps: [
      'Loading ERP product catalogue',
      'Tokenising item descriptions',
      'Scoring match candidates',
      'Ranking results by confidence',
      'Preparing matching interface',
    ],
    accentColor: '#0E9E8F',
    iconBg: 'bg-teal-50',
    stepInterval: 620,
  },
};

export function ProcessingProgress({
  title, subtitle, steps, completedSteps, accentColor, iconBg, titleId, subtitleId,
}: ProgressConfig & { completedSteps: number; titleId?: string; subtitleId?: string }) {
  const progress = (completedSteps / steps.length) * 100;

  return <>
    <div className={`w-16 h-16 rounded-2xl ${iconBg} flex items-center justify-center mx-auto mb-6`}>
      <Loader2 size={28} className="animate-spin motion-reduce:animate-none" style={{ color: accentColor }} />
    </div>

    <div className="text-center mb-7">
      <h2 id={titleId} className="text-gray-900 mb-1.5">{title}</h2>
      <p id={subtitleId} className="text-gray-500 text-sm">{subtitle}</p>
    </div>

    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-6">
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

export function ProcessingScreen({ type }: { type: LoadingType }) {
  const config = CONFIG[type];
  const [completedSteps, setCompletedSteps] = useState(0);

  useEffect(() => {
    setCompletedSteps(0);
    const timers = config.steps.map((_, index) => setTimeout(() => {
      setCompletedSteps(index + 1);
    }, (index + 1) * config.stepInterval));
    return () => timers.forEach(clearTimeout);
  }, [config]);

  return <div className="h-full flex flex-col items-center justify-center p-8 bg-[#F0F2F7]">
    <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 w-full max-w-2xl mb-8">
      <WorkflowStepper currentStep={config.step} />
    </div>
    <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-10 w-full max-w-md">
      <ProcessingProgress {...config} completedSteps={completedSteps} />
    </div>
  </div>;
}
