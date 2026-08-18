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
