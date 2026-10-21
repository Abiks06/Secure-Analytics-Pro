"""Pure-ASGI middleware: request IDs, timing and hardened security headers."""

from __future__ import annotations

import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
_APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' {connect}; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False, connect_src: str = "") -> None:
        self.app = app
        # The SPA talks to Supabase Auth directly, so its origin must be an allowed connect-src.
        self.app_csp = _APP_CSP.format(connect=connect_src).replace("'self' ;", "'self';")
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        is_api = scope["path"].startswith("/api")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                extra = {
                    b"x-request-id": request_id.encode(),
                    b"server-timing": f"app;dur={(time.perf_counter() - started) * 1000:.1f}".encode(),
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-origin",
                    b"content-security-policy": (_API_CSP if is_api else self.app_csp).encode(),
                }
                if is_api:
                    extra[b"cache-control"] = b"no-store"
                if self.hsts:
                    extra[b"strict-transport-security"] = b"max-age=63072000; includeSubDomains"
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in extra.items() if k not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
