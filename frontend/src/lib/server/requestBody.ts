export class RequestBodyTooLarge extends Error {}

export async function readRequestBody(
  request: Request,
  limit = 8 * 1024 * 1024,
): Promise<string> {
  if (Number(request.headers.get('content-length') || 0) > limit) {
    throw new RequestBodyTooLarge('Request body too large');
  }
  if (!request.body) return '';
  const reader = request.body.getReader();
  let body = new Uint8Array(0);
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new RequestBodyTooLarge('Request body too large');
      }
      if (size > body.byteLength) {
        const capacity = Math.min(limit, Math.max(size, body.byteLength * 2, 1024));
        const expanded = new Uint8Array(capacity);
        expanded.set(body);
        body = expanded;
      }
      body.set(value, size - value.byteLength);
    }
  } finally {
    reader.releaseLock();
  }
  return new TextDecoder().decode(body.subarray(0, size));
}
