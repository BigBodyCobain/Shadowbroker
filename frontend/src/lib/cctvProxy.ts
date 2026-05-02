/** Proxy external CCTV URLs through the backend to bypass CORS. */
export function buildCctvProxyUrl(rawUrl: string): string {
  return rawUrl.startsWith('http')
    ? `/api/cctv/media?url=${encodeURIComponent(rawUrl)}`
    : rawUrl;
}
