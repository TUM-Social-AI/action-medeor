import { Check } from 'lucide-react';
import type { WorkflowStep } from '../api/types';

const STEPS: { id: WorkflowStep; label: string }[] = [
  { id: 'ingestion', label: 'Ingestion' },
  { id: 'review', label: 'Review Items' },
  { id: 'matching', label: 'Smart Matching' },
  { id: 'summary', label: 'Summary' },
];

export function WorkflowStepper({ currentStep }: { currentStep: WorkflowStep }) {
  const currentIndex = STEPS.findIndex(step => step.id === currentStep);

  return (
    <div className="flex items-center">
      {STEPS.map((step, index) => {
        const done = index < currentIndex;
        const active = index === currentIndex;

        return (
          <div key={step.id} className="flex items-center">
            {index > 0 && (
              <div className={`w-14 h-px mx-3 ${done ? 'bg-[#0E9E8F]' : 'bg-gray-200'}`} />
            )}
            <div className="flex items-center gap-2">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${
                  done
                    ? 'bg-[#0E9E8F] text-white'
                    : active
                      ? 'bg-[#1B4E8A] text-white'
                      : 'bg-gray-200 text-gray-500'
                }`}
                style={{ fontSize: 12, fontWeight: 600 }}
              >
                {done ? <Check size={13} /> : index + 1}
              </div>
              <span
                className={`text-sm whitespace-nowrap ${
                  done ? 'text-[#0E9E8F]' : active ? 'text-gray-900' : 'text-gray-400'
                }`}
                style={{ fontWeight: active ? 600 : 400 }}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

