import { requestBlob } from '../http';

export async function downloadInquiryExport(inquiryId: string): Promise<void> {
  const file = await requestBlob(`/api/v1/inquiries/${inquiryId}/export.xlsx`);
  const url = URL.createObjectURL(file);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `allocura-${inquiryId}.xlsx`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function fetchRequestResults(requestId: string): Promise<Blob> {
  return requestBlob(`/api/requests/${encodeURIComponent(requestId)}/results.xlsx`);
}

export function saveRequestResults(file: Blob, requestId: string): void {
  const url = URL.createObjectURL(file);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `matched-results-${requestId}.xlsx`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
