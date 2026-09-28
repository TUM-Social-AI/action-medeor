import { ArrowRight } from 'lucide-react';

export function HelpScreen({ onViewHistory }: { onViewHistory: () => void }) {
  return <div className="p-6 max-w-4xl mx-auto">
    <div className="mb-6">
      <h1 className="text-gray-900">Help &amp; Support</h1>
      <p className="text-sm text-gray-500 mt-1">A quick guide to working with partner requests.</p>
    </div>
    <div className="space-y-5">
      <section aria-labelledby="developer-support" className="bg-white rounded-xl border border-gray-200 px-6 py-5">
        <h2 id="developer-support" className="text-gray-900 mb-3">Need more help?</h2>
        <p className="text-sm text-gray-700">For questions or issues these steps do not resolve, reach out to the Allocura developers. Include the request ID and a short description of what happened so we can help.</p>
      </section>
      <section aria-labelledby="request-guide" className="bg-white rounded-xl border border-gray-200 px-6 py-5">
        <h2 id="request-guide" className="text-gray-900 mb-3">Request workflow</h2>
        <ol className="list-decimal pl-5 space-y-2 text-sm text-gray-700">
          <li><strong>Upload:</strong> Select Create Request and upload your partner’s file.</li>
          <li><strong>Review:</strong> Check extracted items, quantities, units, and partner details. Save any corrections before continuing.</li>
          <li><strong>Match:</strong> Review suggested catalog products and confirm your selections.</li>
          <li><strong>Summary:</strong> Check the final request and selected products. Use the summary’s return action if you need to revise matches.</li>
        </ol>
        <p className="text-sm text-gray-500 mt-4">The progress bar at the top shows your current workflow stage.</p>
      </section>
      <section aria-labelledby="upload-help" className="bg-white rounded-xl border border-gray-200 px-6 py-5">
        <h2 id="upload-help" className="text-gray-900 mb-3">Files and upload troubleshooting</h2>
        <p className="text-sm text-gray-700">Supported formats: PDF, Excel (.xlsx, .xls), Word (.docx), and CSV. Maximum file size: 20 MiB.</p>
        <ul className="list-disc pl-5 mt-3 space-y-2 text-sm text-gray-700">
          <li>Include clear item names, quantities, and units so extracted results are easier to review.</li>
          <li>If a file cannot be uploaded, check its format and size, and confirm that it opens correctly on your computer.</li>
          <li>If processing fails, read the error shown on the upload page, check your connection, and try again.</li>
        </ul>
      </section>
      <section aria-labelledby="saved-work" className="bg-white rounded-xl border border-gray-200 px-6 py-5">
        <h2 id="saved-work" className="text-gray-900 mb-3">Reopen saved work</h2>
        <p className="text-sm text-gray-700">Open Request History and select a saved request to return to its current stage. Files selected but not yet uploaded are not saved.</p>
        <div className="mt-5 pt-4 border-t border-gray-100">
          <button onClick={onViewHistory} className="inline-flex items-center gap-2 rounded-md text-sm font-semibold text-[#1B4E8A] hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#1B4E8A]">
            Open Request History <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>
      </section>
    </div>
  </div>;
}
