import { useEffect, useRef, useState } from 'react';
import {
  applyReviewOperation,
  getReview,
  previewReviewOperation,
  undoReviewOperation,
  resolveMissingItem,
} from '../../api/client';
import { ApiError } from '../../api/http';
import type { MissingItemSubmission, ReviewOperation, ReviewPreview, ReviewResponse } from '../../api/types';

export type OperationInput = Omit<ReviewOperation, 'operationId' | 'expectedRevision'>;

export function useReviewOperations(
  requestId: string | null,
  data: ReviewResponse | null,
  refresh: (review: ReviewResponse) => void,
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ operation: ReviewOperation; preview: ReviewPreview } | null>(null);
  const [toast, setToast] = useState<{ message: string; operationId: string | null } | null>(null);
  const [lastUndoId, setLastUndoId] = useState<string | null>(data?.lastUndoOperationId ?? null);
  const inFlight = useRef(false);
  const acceptanceRetry = useRef<{ key: string; operation: ReviewOperation } | null>(null);
  const missingRetry = useRef<{ key: string; submission: MissingItemSubmission } | null>(null);
  useEffect(() => {
    setLastUndoId(data?.lastUndoOperationId ?? null);
  }, [data?.lastUndoOperationId, requestId]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  const recover = async (caught: unknown) => {
    setError(caught instanceof Error ? caught.message : 'Unable to save. Please try again.');
    if (caught instanceof ApiError && caught.status === 409 && requestId) {
      try {
        refresh(await getReview(requestId));
      } catch {
        /* retain the draft and original error */
      }
      setPending(null);
    }
  };
  const preview = async (input: OperationInput) => {
    if (!requestId || !data || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    const operation: ReviewOperation = {
      ...input,
      operationId: crypto.randomUUID(),
      expectedRevision: data.reviewRevision ?? 0,
    };
    try {
      setPending({ operation, preview: await previewReviewOperation(requestId, operation) });
    } catch (caught) {
      await recover(caught);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  const save = async (operation: ReviewOperation) => {
    const result = await applyReviewOperation(requestId!, operation);
    refresh(result.review);
    setLastUndoId(result.operationId);
    setPending(null);
    const label = {
      edit: 'Updated',
      quantity_rule: 'Updated quantities for',
      verify: 'Verified',
      accept: 'Reviewed',
      remove: 'Removed',
      restore: 'Restored',
      column_mapping: 'Updated source columns for',
    }[operation.action];
    const mapping =
      operation.action === 'accept'
        ? data?.issues?.find(
            (issue) => issue.scope === 'table' && operation.issueIds?.includes(issue.id),
          )
        : null;
    setToast({
      message: mapping
        ? `Confirmed columns for ${mapping.itemIds?.length ?? 0} items`
        : `${label} ${operation.itemIds.length || 'document'}${operation.itemIds.length ? (operation.itemIds.length === 1 ? ' item' : ' items') : ''}`,
      operationId: result.operationId,
    });
  };
  const apply = async () => {
    if (!requestId || !pending || inFlight.current) return false;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await save(pending.operation);
      return true;
    } catch (caught) {
      await recover(caught);
      return false;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  // The visible values and this explicit action are the confirmation. Server validation,
  // issue scoping and undo are identical to the preview/apply path.
  const accept = async (input: Pick<OperationInput, 'itemIds' | 'issueIds'>) => {
    if (!requestId || !data || !input.issueIds?.length || inFlight.current) return false;
    const selection = { itemIds: [...input.itemIds].sort((a, b) => a - b), issueIds: [...input.issueIds].sort() };
    const key = JSON.stringify([requestId, data.reviewRevision, selection]);
    if (acceptanceRetry.current?.key !== key) {
      acceptanceRetry.current = { key, operation: { ...selection, action: 'accept',
        operationId: crypto.randomUUID(), expectedRevision: data.reviewRevision ?? 0 } };
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await save(acceptanceRetry.current.operation);
      acceptanceRetry.current = null;
      return true;
    } catch (caught) {
      await recover(caught);
      return false;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  const resolveMissing = async (input: Omit<MissingItemSubmission, 'operationId' | 'expectedRevision'>) => {
    if (!requestId || !data || inFlight.current) return false;
    const key = JSON.stringify([requestId, data.reviewRevision, input]);
    if (missingRetry.current?.key !== key) missingRetry.current = { key, submission: {
      ...input, operationId: crypto.randomUUID(), expectedRevision: data.reviewRevision ?? 0,
    } };
    inFlight.current = true; setBusy(true); setError(null);
    try {
      const result = await resolveMissingItem(requestId, missingRetry.current.submission);
      refresh(result.review); setLastUndoId(result.operationId); setPending(null);
      const item = result.review.items.find(item => item.id === result.itemId);
      setToast({ message: item ? `Missing item filled: ${item.name} · ${item.quantity?.toLocaleString()} ${item.unit}` : 'Missing item filled', operationId: result.operationId });
      missingRetry.current = null;
      return true;
    } catch (caught) { await recover(caught); return false; }
    finally { inFlight.current = false; setBusy(false); }
  };
  const undo = async () => {
    if (!requestId || !lastUndoId || !data || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await undoReviewOperation(requestId, lastUndoId, data.reviewRevision ?? 0);
      refresh(result.review);
      setLastUndoId(null);
      setToast({ message: 'Operation undone', operationId: null });
    } catch (caught) {
      await recover(caught);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return { busy, error, setError, pending, setPending, preview, apply, accept, resolveMissing, undo, toast, setToast, lastUndoId };
}

export type ReviewOperations = ReturnType<typeof useReviewOperations>;
