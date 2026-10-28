import type { ExtractedItem } from '../../api/types';

export function filterItems(
  items: ExtractedItem[],
  search: string,
  state: string,
  type: string,
  category: string,
  categoryItems: Set<number>,
) {
  const term = search.trim().toLocaleLowerCase();
  return items.filter(
    (item) =>
      (!term || `${item.name} ${item.itemNumber ?? ''}`.toLocaleLowerCase().includes(term)) &&
      (state === 'all' || (state === 'ready' ? item.status === 'verified' : item.status !== 'verified')) &&
      (type === 'all' || item.domain === type) &&
      (category === 'all' || categoryItems.has(item.id)),
  );
}

export function toggleSelection(selected: Set<number>, id: number, checked: boolean) {
  const next = new Set(selected);
  if (checked) next.add(id);
  else next.delete(id);
  return next;
}
