"""Bound request bodies before any handler buffers or parses them."""

from starlette.responses import JSONResponse


def request_body_limit(path: str) -> int:
    path = path.rstrip("/")
    if path in {"/api/mesh/infonet/peer-push", "/api/mesh/gate/peer-push"}:
        return 512 * 1024
    if path in {"/api/mesh/infonet/peer-announce", "/api/mesh/dm/replicate"}:
        return 64 * 1024
    return 8 * 1024 * 1024


class RequestBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        limit = request_body_limit(scope["path"])
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        body = bytearray()
        total = 0
        if declared <= limit:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                total += len(message.get("body", b""))
                if total > limit:
                    break
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    buffered = {"type": "http.request", "body": bytes(body), "more_body": False}
                    body.clear()

                    async def replay():
                        nonlocal buffered
                        if buffered is not None:
                            message, buffered = buffered, None
                            return message
                        return await receive()

                    return await self.app(scope, replay, send)
        response = JSONResponse(
            {"detail": "Request body too large"},
            status_code=413,
            headers={"Cache-Control": "no-store", "Connection": "close"},
        )
        await response(scope, receive, send)
