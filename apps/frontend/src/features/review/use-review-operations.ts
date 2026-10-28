import { useEffect, useRef, useState } from 'react';
import {
  applyReviewOperation,
  getReview,
  previewReviewOperation,
  undoReviewOperation,
} from '../../api/client';
import { ApiError } from '../../api/http';
import type { ReviewOperation, ReviewPreview, ReviewResponse } from '../../api/types';

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
  const apply = async () => {
    if (!requestId || !pending || inFlight.current) return false;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await applyReviewOperation(requestId, pending.operation);
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
      }[pending.operation.action];
      const mapping =
        pending.operation.action === 'accept'
          ? data?.issues?.find(
              (issue) => issue.scope === 'table' && pending.operation.issueIds?.includes(issue.id),
            )
          : null;
      setToast({
        message: mapping
          ? `Confirmed columns for ${mapping.itemIds?.length ?? 0} items`
          : `${label} ${pending.operation.itemIds.length || 'document'}${pending.operation.itemIds.length ? (pending.operation.itemIds.length === 1 ? ' item' : ' items') : ''}`,
        operationId: result.operationId,
      });
      return true;
    } catch (caught) {
      await recover(caught);
      return false;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
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
  return { busy, error, setError, pending, setPending, preview, apply, undo, toast, setToast, lastUndoId };
}

export type ReviewOperations = ReturnType<typeof useReviewOperations>;
