import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketClose

PARAMETER = "token"
REFUSED = (
    "<p style='font-family: sans-serif'>Open the link that labcatalog printed when it started; "
    "it holds the key to this window.</p>"
)


class Gate:
    # Anyone on the same computer can reach a local port, so only holders of this run's key get in.
    def __init__(self, app: ASGIApp, token: str, port: int) -> None:
        self.app, self.token = app, token
        # Cookies are kept per host, not per port, so each run names its own.
        self.cookie = f"labcatalog_{port}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if self.holds(self.cookie_of(scope)):
            await self.app(scope, receive, send)
        elif scope["type"] == "http" and self.holds(self.query_of(scope)):
            await self.app(scope, receive, self.remembered(send))
        elif scope["type"] == "http":
            await HTMLResponse(REFUSED, status_code=403)(scope, receive, send)
        else:
            await WebSocketClose(code=1008)(scope, receive, send)

    def holds(self, given: str | None) -> bool:
        return given is not None and secrets.compare_digest(given, self.token)

    def cookie_of(self, scope: Scope) -> str | None:
        for name, value in scope["headers"]:
            if name == b"cookie":
                found = SimpleCookie(value.decode("latin-1")).get(self.cookie)
                if found is not None:
                    return found.value
        return None

    def query_of(self, scope: Scope) -> str | None:
        values = parse_qs(scope["query_string"].decode("latin-1")).get(PARAMETER)
        return values[0] if values else None

    def remembered(self, send: Send) -> Send:
        # The first page opened with the key sets it as a cookie for every request after.
        async def sending(message: Message) -> None:
            if message["type"] == "http.response.start":
                cookie = f"{self.cookie}={self.token}; Path=/; HttpOnly; SameSite=Strict"
                message["headers"] = [*message["headers"], (b"set-cookie", cookie.encode())]
            await send(message)

        return sending
