/**
 * DEPRECATED — Gate SSE stream removed in S3A.
 * The frontend now relies on the authenticated poll loop for gate refresh.
 * This stub is kept so stale imports compile without error.
 */
export function useGateSSE(_onEvent: (gateId: string) => void) {
  // no-op
}
