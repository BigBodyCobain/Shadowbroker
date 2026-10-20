/** Proxy Telegram CDN media through the backend (host allowlist + range requests). */
export function buildTelegramMediaProxyUrl(rawUrl: string): string {
  return rawUrl.startsWith('http')
    ? `/api/telegram/media?url=${encodeURIComponent(rawUrl)}`
    : rawUrl;
}
