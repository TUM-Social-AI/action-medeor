import { useEffect, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';
import type { LoadingType, WorkflowStep } from '../api/types';
import { WorkflowStepper } from './WorkflowStepper';

const CONFIG: Record<
  LoadingType,
  {
    step: WorkflowStep;
    title: string;
    subtitle: string;
    steps: string[];
    accentColor: string;
    iconBg: string;
    stepInterval: number;
  }
> = {
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

export function ProcessingScreen({ type }: { type: LoadingType }) {
  const config = CONFIG[type];
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    config.steps.forEach((_, index) => {
      const timer = setTimeout(() => {
        setCompletedSteps(prev => [...prev, index]);
        setActiveStep(index + 1);
      }, (index + 1) * config.stepInterval);
      timers.push(timer);
    });

    return () => timers.forEach(clearTimeout);
  }, [config]);

  const progress = (completedSteps.length / config.steps.length) * 100;

  return (
    <div className="h-full flex flex-col items-center justify-center p-8 bg-[#F0F2F7]">
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-4 w-full max-w-2xl mb-8">
        <WorkflowStepper currentStep={config.step} />
      </div>

      <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-10 w-full max-w-md">
        <div className={`w-16 h-16 rounded-2xl ${config.iconBg} flex items-center justify-center mx-auto mb-6`}>
          <Loader2 size={28} className="animate-spin" style={{ color: config.accentColor }} />
        </div>

        <div className="text-center mb-7">
          <h2 className="text-gray-900 mb-1.5">{config.title}</h2>
          <p className="text-gray-500 text-sm">{config.subtitle}</p>
        </div>

        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-6">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progress}%`, backgroundColor: config.accentColor }}
          />
        </div>

        <div className="space-y-3">
          {config.steps.map((label, index) => {
            const done = completedSteps.includes(index);
            const active = activeStep === index;

            return (
              <div
                key={label}
                className={`flex items-center gap-3 transition-colors duration-300 ${
                  done ? 'text-gray-400' : active ? 'text-gray-800' : 'text-gray-300'
                }`}
                style={{ fontSize: 13 }}
              >
                <div
                  className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 transition-all ${
                    done ? 'bg-green-100' : active ? config.iconBg : 'bg-gray-100'
                  }`}
                >
                  {done ? (
                    <Check size={11} className="text-green-600" />
                  ) : (
                    <div
                      className={`w-2 h-2 rounded-full ${active ? 'animate-pulse' : ''}`}
                      style={{ backgroundColor: active ? config.accentColor : '#D1D5DB' }}
                    />
                  )}
                </div>
                {label}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

