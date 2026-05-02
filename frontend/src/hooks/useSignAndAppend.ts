/**
 * useSignAndAppend — shared submission state for any view that needs
 * to sign + post an Infonet economy event.
 *
 * Wraps ``signAndAppend`` from ``@/mesh/infonetEconomyClient`` with
 * React loading / result state. Each view tracks its own per-action
 * status independently — the hook returns ``submit(event_type,
 * payload)`` plus the latest ``result`` and ``state`` flags.
 *
 * Cross-cutting non-hostile UX rule: ``result.reason`` on failure
 * carries the verbatim diagnostic from the backend so the view
 * surfaces it directly. Never display "denied" with no detail.
 */

import { useCallback, useState } from 'react';
import {
  signAndAppend,
  type AppendResult,
} from '@/mesh/infonetEconomyClient';

export type SubmitState = 'idle' | 'submitting' | 'success' | 'error';

export interface UseSignAndAppendReturn {
  state: SubmitState;
  result: AppendResult | null;
  submit: (
    event_type: string,
    payload: Record<string, unknown>,
  ) => Promise<AppendResult>;
  reset: () => void;
}

export function useSignAndAppend(): UseSignAndAppendReturn {
  const [state, setState] = useState<SubmitState>('idle');
  const [result, setResult] = useState<AppendResult | null>(null);

  const submit = useCallback(
    async (event_type: string, payload: Record<string, unknown>) => {
      setState('submitting');
      let res: AppendResult;
      try {
        res = await signAndAppend({ event_type, payload });
      } catch (err) {
        res = {
          ok: false,
          reason: err instanceof Error ? err.message : 'unknown_error',
        };
      }
      setResult(res);
      setState(res.ok ? 'success' : 'error');
      return res;
    },
    [],
  );

  const reset = useCallback(() => {
    setState('idle');
    setResult(null);
  }, []);

  return { state, result, submit, reset };
}
