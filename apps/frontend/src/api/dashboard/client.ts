import { requestJson } from '../http';

export type DashboardSummaryV1 = {
  as_of: string;
  inquiries_total: number;
  inquiries_completed: number;
  lines_total: number;
  lines_matched: number;
  lines_requiring_review: number;
  average_processing_seconds?: number | null;
};

export function getDashboardSummary() {
  return requestJson<DashboardSummaryV1>('/api/v1/dashboard/summary');
}
