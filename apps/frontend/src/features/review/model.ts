import type { ExtractedItem, ReviewIssue } from '../../api/types';

export function isReady(item: ExtractedItem) {
  return item.readyForMatching ?? item.status === 'verified';
}

/** Readiness and who checked the source are separate facts. Never invent AI or human provenance. */
export function reviewPresentation(item: ExtractedItem, issues: ReviewIssue[] = []) {
  const related = issues.filter((issue) => issue.itemId === item.id || issue.itemIds?.includes(item.id));
  if (!isReady(item)) {
    const sharedOnly =
      related.some((issue) => issue.state === 'open') &&
      related.filter((issue) => issue.state === 'open').every((issue) => issue.scope === 'table');
    return {
      label: sharedOnly ? 'Shared check pending' : 'Needs human review',
      description: sharedOnly
        ? 'Confirm the columns once in guided review.'
        : 'Resolve the open problems before matching.',
      tone: 'pending' as const,
    };
  }
  if (item.manual)
    return {
      label: 'Manually entered',
      description: 'Entered by a person; required values are valid.',
      tone: 'ready' as const,
    };
  if (item.verificationSource === 'human')
    return {
      label: 'Human verified',
      description: 'A person explicitly verified the whole item.',
      tone: 'ready' as const,
    };
  if (item.verificationSource === 'ai')
    return {
      label: 'AI checked',
      description: 'AI checked this item against its source. No further verification is required.',
      tone: 'ready' as const,
    };
  if (
    Object.values(item.fieldReviews ?? {}).some((review) => review.source === 'human') ||
    related.some((issue) => issue.state === 'accepted')
  ) {
    return {
      label: 'Human reviewed',
      description: 'Flagged fields or source layout were reviewed by a person. All remaining checks passed.',
      tone: 'ready' as const,
    };
  }
  return {
    label: 'Checks passed',
    description: 'Validation passed. No whole-item AI or human verification is recorded.',
    tone: 'ready' as const,
  };
}

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
      (state === 'all' || (state === 'ready' ? isReady(item) : !isReady(item))) &&
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
