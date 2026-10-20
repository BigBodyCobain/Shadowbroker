/**
 * Wormhole teardown logic extracted from InfonetTerminal close handler.
 * Delegates to the terminal session lifecycle so background prep is aborted too.
 */
import { endInfonetTerminalSession } from '@/lib/infonetTerminalSession';

export async function teardownWormholeOnClose(
  _fetchState?: (force: boolean) => Promise<{ ready?: boolean; running?: boolean } | null>,
  _leave?: () => Promise<unknown>,
): Promise<void> {
  await endInfonetTerminalSession();
}
