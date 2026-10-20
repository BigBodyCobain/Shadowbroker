/**
 * Signal-style DM connect helpers — paste a short address or full invite blob.
 */

export function isLikelyDmShortAddress(value: string): boolean {
  const trimmed = value.trim();
  return (
    !trimmed.startsWith('{') &&
    !trimmed.startsWith('[') &&
    /^[a-zA-Z0-9_.:-]{16,}$/.test(trimmed)
  );
}

export function parseDmInviteImportBlob(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (!trimmed) {
    throw new Error('Paste a contact address first.');
  }
  if (isLikelyDmShortAddress(trimmed)) {
    return { short_address: trimmed };
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('Contact address must be a signed address object.');
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error('That does not look like a contact address. Paste what they copied from Secure Messages.');
    }
    throw error;
  }
}

export function inviteFromParsedBlob(parsed: Record<string, unknown>): Record<string, unknown> {
  const nested = parsed.invite;
  if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
    return nested as Record<string, unknown>;
  }
  return parsed;
}

export function shortHandle(peerId: string): string {
  const value = String(peerId || '').trim();
  if (!value) return 'unknown';
  if (value.length <= 18) return value;
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}
