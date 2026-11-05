import type { ExtractedItem, ReviewIssue, ReviewTask } from '../../api/types';

const labels: Record<string, string> = {
  domain: 'Product type', quantity: 'Quantity', unit: 'Unit', name: 'Product name',
  notes: 'Notes', item_number: 'Item number', shelf_life: 'Shelf life', priority: 'Priority',
};

function display(item: ExtractedItem, field: string): string {
  const key = field === 'item_number' ? 'itemNumber' : field === 'shelf_life' ? 'shelfLife' : field;
  const value = item[key as keyof ExtractedItem];
  return typeof value === 'number' ? value.toLocaleString() : typeof value === 'string' && value ? value : 'Missing';
}

export function guidedFields(task: ReviewTask, issue?: ReviewIssue): string[] {
  if (task.category === 'type') return ['domain'];
  if (task.category === 'unit') return ['unit'];
  if (task.category === 'quantity' || task.category === 'totals') return ['quantity'];
  if (task.category === 'description') return ['name'];
  return issue?.fields?.length ? issue.fields : ['quantity', 'unit', 'domain'];
}

export function guidedValues(task: ReviewTask, item: ExtractedItem, issue?: ReviewIssue) {
  if (task.code === 'non_item_row') return [{ field: 'row', label: 'Extracted as', value: 'Product item' }];
  return guidedFields(task, issue).map(field => ({
    field, label: labels[field] ?? field, value: display(item, field),
  }));
}

export function guidedColumnLabel(task: ReviewTask): string {
  const field = guidedFields(task)[0];
  return ['type', 'unit', 'quantity', 'totals', 'description'].includes(task.category)
    ? `Extracted ${labels[field].toLowerCase()}` : 'Extracted details';
}

export function keepLabel(task: ReviewTask): string {
  if (task.code === 'non_item_row') return 'Keep as product row';
  return ({ type: 'Keep type', unit: 'Keep unit', quantity: 'Keep extracted value',
    totals: 'Keep extracted value', description: 'Keep description' } as Record<string, string>)[task.category]
    ?? 'Keep extracted values';
}

/** Show known alternatives explicitly; uncertainty never supplies a made-up replacement. */
export function guidedExpectation(task: ReviewTask, item: ExtractedItem, issue?: ReviewIssue) {
  const source = issue?.sourceValues ?? {};
  if (task.code === 'non_item_row') return { label: 'Expected row', value: 'Column headings, not a product', detail: 'Remove this row from the request.' };
  if (task.category === 'unit') {
    if (source.unit) return { label: 'Source unit', value: source.unit };
    if (issue?.suggestedValue) return { label: 'Suggested unit', value: issue.suggestedValue };
    return { label: 'Expected unit', value: 'Not established', detail: `Confirm what one “${item.unit || 'unit'}” counts in the source.` };
  }
  if (task.category === 'type') return { label: source.domain ? 'Source type' : 'Expected type',
    value: source.domain || issue?.suggestedValue || 'Choose Equipment or Medicine.' };
  if (task.category === 'quantity' || task.category === 'totals') {
    if (task.code === 'pack_total_conflict' && (issue?.packs ?? 0) > 0 && (issue?.unitsPerPack ?? 0) > 0 && (issue?.calculatedTotal ?? 0) > 0)
      return { label: 'Pack calculation', value: `${issue!.packs!.toLocaleString()} × ${issue!.unitsPerPack!.toLocaleString()} = ${issue!.calculatedTotal!.toLocaleString()} ≠ ${(issue?.requestedTotal ?? item.quantity)?.toLocaleString() ?? 'Missing'}`, detail: 'The pack total conflicts with the stated requested total.' };
    if (Number.isInteger(issue?.requestedTotal) && (issue?.requestedTotal ?? 0) > 0)
      return { label: 'Source quantity', value: issue!.requestedTotal!.toLocaleString() };
    return { label: 'Expected quantity', value: '> 0 · whole number' };
  }
  if (task.category === 'description') return { label: source.name ? 'Source description' : 'Check description',
    value: source.name || issue?.message || 'Compare the complete product name, strength and presentation with the source.' };
  if (/unsupported source column|AI correction .*cited a (source column|missing or empty source cell)/i.test(issue?.message ?? ''))
    return { label: 'AI correction not applied', value: 'The cited cell did not support the proposed change. Check the extracted fields against the source.' };
  if (issue?.code === 'low_confidence' || issue?.code === 'confirmation_required')
    return { label: 'Values to verify', value: 'Compare this row with the source.' };
  return { label: 'What needs checking', value: issue?.message || 'Compare these details with the original source.' };
}
