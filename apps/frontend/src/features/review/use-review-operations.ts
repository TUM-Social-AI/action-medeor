import { useRef, useState } from 'react';
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
  const inFlight = useRef(false);

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
      setPending(null);
      const label = {
        edit: 'Updated',
        quantity_rule: 'Updated quantities for',
        verify: 'Verified',
        accept: 'Reviewed',
        remove: 'Removed',
        restore: 'Restored',
      }[pending.operation.action];
      setToast({
        message: `${label} ${pending.operation.itemIds.length || 'document'}${pending.operation.itemIds.length ? ' items' : ''}`,
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
    if (!requestId || !toast?.operationId || !data || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await undoReviewOperation(requestId, toast.operationId, data.reviewRevision ?? 0);
      refresh(result.review);
      setToast({ message: 'Operation undone', operationId: null });
    } catch (caught) {
      await recover(caught);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return { busy, error, setError, pending, setPending, preview, apply, undo, toast, setToast };
}

export type ReviewOperations = ReturnType<typeof useReviewOperations>;
