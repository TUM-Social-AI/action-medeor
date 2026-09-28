export function SettingsScreen() {
  return <div className="p-6 max-w-6xl mx-auto">
    <div className="mb-6">
      <h1 className="text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500 mt-1">Information about your procurement workspace.</p>
    </div>
    <section aria-labelledby="app-information" className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 id="app-information" className="text-gray-900 mb-4">App information</h2>
      <dl className="grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-x-6 gap-y-3 text-sm">
        <dt className="text-gray-500">Application</dt><dd className="text-gray-900">Allocura</dd>
        <dt className="text-gray-500">Workspace</dt><dd className="text-gray-900">action medeor — Procurement</dd>
        <dt className="text-gray-500">Purpose</dt><dd className="text-gray-900">Review partner requests and match requested supplies to catalog products.</dd>
        <dt className="text-gray-500">Supported imports</dt><dd className="text-gray-900">PDF, Excel (.xlsx, .xls), Word (.docx), and CSV</dd>
      </dl>
    </section>
  </div>;
}
