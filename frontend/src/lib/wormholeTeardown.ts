/**
 * Wormhole teardown logic extracted from InfonetTerminal close handler.
 * Shuts down Wormhole when the terminal closes so it doesn't stay running.
 */
export async function teardownWormholeOnClose(
  fetchState: (force: boolean) => Promise<{ ready?: boolean; running?: boolean } | null>,
  leave: () => Promise<unknown>,
): Promise<void> {
  try {
    const s = await fetchState(false);
    if (s?.ready || s?.running) {
      await leave();
    }
  } catch {
    /* ignore — best-effort teardown */
  }
}
