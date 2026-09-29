import { Check } from 'lucide-react';
import type { WorkflowStep } from '../api/types';

const STEPS: { id: WorkflowStep; label: string; shortLabel: string }[] = [
  { id: 'ingestion', label: 'Ingestion', shortLabel: 'Ingestion' },
  { id: 'review', label: 'Review Items', shortLabel: 'Review' },
  { id: 'matching', label: 'Smart Matching', shortLabel: 'Matching' },
  { id: 'summary', label: 'Summary', shortLabel: 'Summary' },
];

export function WorkflowStepper({ currentStep }: { currentStep: WorkflowStep }) {
  const currentIndex = STEPS.findIndex(step => step.id === currentStep);

  return <nav className="workflow-stepper" aria-label="Request progress">
    <ol className="workflow-stepper__track">
      {STEPS.map((step, index) => {
        const done = index < currentIndex;
        const active = index === currentIndex;
        return <li key={step.id} className="workflow-stepper__item" aria-current={active ? 'step' : undefined} aria-label={`${step.label}, ${done ? 'complete' : active ? 'current' : 'upcoming'}`}>
          {index > 0 && <span className={'workflow-stepper__connector ' + (done ? 'bg-[#0E9E8F]' : 'bg-gray-200')} aria-hidden="true" />}
          <span className="workflow-stepper__node" aria-hidden="true">
            <span className={'workflow-stepper__circle flex items-center justify-center rounded-full flex-shrink-0 ' + (done ? 'bg-[#0E9E8F] text-white' : active ? 'bg-[#1B4E8A] text-white' : 'bg-gray-200 text-gray-500')}>
              {done ? <Check size={13} /> : index + 1}
            </span>
            <span className={'workflow-stepper__label whitespace-nowrap text-sm ' + (done ? 'text-[#0E9E8F]' : active ? 'text-gray-900 font-semibold' : 'text-gray-400')} data-active={active}>
              <span className="workflow-stepper__full">{step.label}</span>
              <span className="workflow-stepper__short">{step.shortLabel}</span>
            </span>
          </span>
        </li>;
      })}
    </ol>
  </nav>;
}
