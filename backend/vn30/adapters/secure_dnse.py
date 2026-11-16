"""Production-only, read-only DNSE transport; not connected to the MOCK service.

Wire signing follows dnse-tech/openapi-sdk at aa55a5117de2534707bca6165b6738e1cc6fc6a4.
Callers must verify the security/network gates before using authenticated methods.
No transport output, response bodies, SDK debug, or credentials are logged or stored.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import websockets

from ..connectivity import required_context

REST_HOST = "https://openapi.dnse.com.vn"
WS_HOST = "wss://ws-openapi.dnse.com.vn/v1/stream?encoding=json"
API_VERSION = "2026-07-23"
MAX_RESPONSE = 1024 * 1024
# Production authentication stays blocked until the security and network gates are verified.
_AUTHENTICATED_IO_ENABLED = False


class TransportError(Exception):
    """Fixed category only; never include server text, URLs, or headers."""

    def __init__(self, category, *, http_status=None):
        super().__init__(category)
        self.http_status = http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None


@dataclass(frozen=True, repr=False)
class Credentials:
    key: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_environment(cls):
        key, secret = os.getenv("DNSE_API_KEY"), os.getenv("DNSE_API_SECRET")
        if not key or not secret:
            raise TransportError("missing_credentials")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,256}", key):
            raise TransportError("invalid_credential_format")
        return cls(key, secret)

    def __repr__(self):
        return "Credentials([REDACTED])"


def rest_headers(credentials, path, date, nonce):
    """The official SDK signs the path (excluding query) plus Date and nonce."""
    signing = f"(request-target): get {path}\ndate: {date}\nnonce: {nonce}"
    digest = hmac.new(credentials.secret.encode(), signing.encode(), hashlib.sha256).digest()
    signature = urllib.parse.quote(base64.b64encode(digest).decode(), safe="")
    auth = (
        f'Signature keyId="{credentials.key}",algorithm="hmac-sha256",'
        f'headers="(request-target) date",signature="{signature}",nonce="{nonce}"'
    )
    return {"Date": date, "X-Signature": auth, "x-api-key": credentials.key, "version": API_VERSION}


def ws_auth(credentials, timestamp, nonce):
    data = f"{credentials.key}:{timestamp}:{nonce}"
    signature = hmac.new(credentials.secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return {
        "action": "auth",
        "api_key": credentials.key,
        "signature": signature,
        "timestamp": timestamp,
        "nonce": nonce,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _symbol(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value):
        raise ValueError("invalid_symbol")
    return value


def read_only_path(operation, symbol=None):
    paths = {
        "instruments": "/market/instruments",
        "ohlc": "/price/ohlc",
        "session": "/market/trading-session",
    }
    if operation in paths:
        return paths[operation]
    if operation in {"security_definition", "trades", "quotes"} and symbol:
        suffix = {"security_definition": "secdef", "trades": "trades", "quotes": "quotes"}[operation]
        return f"/price/{_symbol(symbol)}/{suffix}"
    raise ValueError("unsupported_read_only_operation")


class SecureREST:
    """GET-only production transport. Response data stays in memory."""

    def __init__(self, credentials, *, timeout=5, authorized=False):
        if not 0 < timeout <= 10:
            raise ValueError("invalid_timeout")
        self._credentials = credentials
        self._timeout = timeout
        self._authorized = authorized
        self.last_http_status = None
        # Default ProxyHandler honors the managed environment; TLS still verifies host and chain.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),
            urllib.request.HTTPSHandler(context=required_context(), debuglevel=0),
            NoRedirect(),
        )

    def get(self, operation, *, symbol=None, query=None):
        self.last_http_status = None
        path = read_only_path(operation, symbol)
        if not (_AUTHENTICATED_IO_ENABLED or self._authorized):
            raise TransportError("security_gate_not_approved")
        url = REST_HOST + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        request = urllib.request.Request(
            url, headers=rest_headers(self._credentials, path, date, uuid.uuid4().hex), method="GET"
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                self.last_http_status = getattr(response, "status", None)
                payload = response.read(MAX_RESPONSE + 1)
                if len(payload) > MAX_RESPONSE:
                    raise TransportError("response_too_large")
                try:
                    return json.loads(payload)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise TransportError("invalid_json") from None
        except urllib.error.HTTPError as error:
            status = error.code
            self.last_http_status = status
            error.close()
            if status in (401, 403):
                category = "authentication_or_authorization_rejected"
            elif status == 429:
                category = "rate_limited"
            elif 300 <= status < 400:
                category = "redirect_blocked"
            else:
                category = "http_error"
            raise TransportError(category, http_status=status) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise TransportError("network_or_tls_error") from None


class SecureStream:
    """A bounded single WSS session; no SDK logging, reconnect, or persistence."""

    def __init__(self, credentials, *, timeout=5, authorized=False):
        if not 0 < timeout <= 10:
            raise ValueError("invalid_timeout")
        self._credentials, self._timeout, self._authorized = credentials, timeout, authorized

    async def sample(
        self, symbol, board_id, *, duration=5, max_messages=20, on_authenticated=None, on_message=None
    ):
        _symbol(symbol)
        _symbol(board_id)
        if not (_AUTHENTICATED_IO_ENABLED or self._authorized):
            raise TransportError("security_gate_not_approved")
        if not 0 < duration <= 15 or not 1 <= max_messages <= 100:
            raise ValueError("invalid_sample_bounds")
        quiet = logging.getLogger("vn30.dnse.private_transport")
        quiet.disabled = True
        try:
            async with asyncio.timeout(self._timeout + duration + 2):
                async with websockets.connect(
                    WS_HOST,
                    ssl=required_context(),
                    logger=quiet,
                    open_timeout=self._timeout,
                    close_timeout=1,
                    max_size=MAX_RESPONSE,
                ) as ws:
                    welcome = json.loads(await asyncio.wait_for(ws.recv(), self._timeout))
                    if not isinstance(welcome, dict) or not (welcome.get("session_id") or welcome.get("sid")):
                        raise TransportError("unexpected_welcome")
                    nonce = str(time.time_ns() // 1000)
                    await ws.send(json.dumps(ws_auth(self._credentials, int(time.time()), nonce)))
                    auth = json.loads(await asyncio.wait_for(ws.recv(), self._timeout))
                    if not isinstance(auth, dict) or (auth.get("action") or auth.get("a")) != "auth_success":
                        raise TransportError("authentication_or_authorization_rejected")
                    if on_authenticated is not None:
                        on_authenticated()
                    channels = [
                        {"name": f"tick_extra.{board_id}.json", "symbols": [symbol]},
                        {"name": f"top_price.{board_id}.json", "symbols": [symbol]},
                        {"name": "market_index.VN30.json", "symbols": []},
                    ]
                    for channel in channels:
                        await ws.send(json.dumps({"action": "subscribe", "channels": [channel]}))
                    messages = []
                    deadline = asyncio.get_running_loop().time() + duration
                    while len(messages) < max_messages:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            break
                        try:
                            msg = await asyncio.wait_for(ws.recv(), remaining)
                            received = datetime.now(timezone.utc)
                        except TimeoutError:
                            break
                        data = json.loads(msg)
                        if not isinstance(data, dict):
                            continue
                        action = data.get("action") or data.get("a")
                        if action == "ping":
                            await ws.send(json.dumps({"action": "pong"}))
                        elif action == "error":
                            if data.get("channel") != "market_index.VN30.json":
                                raise TransportError("websocket_subscription_error")
                        elif data.get("T") in {"te", "q", "mi", "emi", "s"}:
                            messages.append(data)
                            if on_message is not None:
                                await on_message(data, received)
                    return messages
        except TransportError:
            raise
        except (OSError, TimeoutError, ValueError, websockets.exceptions.WebSocketException):
            raise TransportError("websocket_transport_or_protocol_error") from None


async def preflight_rest():
    """Verify REST TLS over the configured route without authentication."""

    def check_rest():
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),
            urllib.request.HTTPSHandler(context=required_context(), debuglevel=0),
            NoRedirect(),
        )
        try:
            with opener.open(urllib.request.Request(REST_HOST + "/", method="HEAD"), timeout=5):
                return
        except urllib.error.HTTPError as exc:
            # An HTTP response from the origin is sufficient for this unauthenticated check.
            exc.close()
            return
        except (urllib.error.URLError, OSError, TimeoutError):
            raise TransportError("network_blocked") from None

    await asyncio.to_thread(check_rest)


async def preflight_ws():
    """Verify the unauthenticated WSS handshake independently of REST."""
    quiet = logging.getLogger("vn30.dnse.private_transport")
    quiet.disabled = True
    try:
        async with asyncio.timeout(7):
            async with websockets.connect(
                WS_HOST,
                ssl=required_context(),
                logger=quiet,
                open_timeout=5,
                close_timeout=1,
                max_size=MAX_RESPONSE,
            ) as ws:
                welcome = json.loads(await ws.recv())
                if not isinstance(welcome, dict) or not (welcome.get("session_id") or welcome.get("sid")):
                    raise TransportError("unexpected_welcome")
    except TransportError:
        raise
    except (OSError, TimeoutError, ValueError, websockets.exceptions.WebSocketException):
        raise TransportError("network_blocked") from None


async def preflight():
    """Application gate: both endpoints must be reachable before starting LIVE."""
    await preflight_rest()
    await preflight_ws()


async def stream_market(credentials, symbol, board_id, on_connect, on_message):
    """Caller must have verified preflight; consume frames in memory, never log them."""
    _symbol(symbol)
    _symbol(board_id)
    quiet = logging.getLogger("vn30.dnse.private_transport")
    quiet.disabled = True
    try:
        async with websockets.connect(
            WS_HOST,
            ssl=required_context(),
            logger=quiet,
            open_timeout=5,
            close_timeout=1,
            max_size=MAX_RESPONSE,
        ) as ws:
            welcome = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if not isinstance(welcome, dict) or not (welcome.get("session_id") or welcome.get("sid")):
                raise TransportError("unexpected_welcome")
            await ws.send(json.dumps(ws_auth(credentials, int(time.time()), str(time.time_ns() // 1000))))
            auth = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if not isinstance(auth, dict) or (auth.get("action") or auth.get("a")) != "auth_success":
                raise TransportError("authentication_or_authorization_rejected")
            channels = [
                {"name": f"tick_extra.{board_id}.json", "symbols": [symbol]},
                {"name": f"top_price.{board_id}.json", "symbols": [symbol]},
                {"name": "market_index.VN30.json", "symbols": []},
            ]
            for channel in channels:
                await ws.send(json.dumps({"action": "subscribe", "channels": [channel]}))
            await on_connect()
            async for raw in ws:
                received = datetime.now(timezone.utc)
                data = json.loads(raw)
                if not isinstance(data, dict):
                    continue
                action = data.get("action") or data.get("a")
                if action == "ping":
                    await ws.send(json.dumps({"action": "pong"}))
                elif action == "error":
                    if data.get("channel") != "market_index.VN30.json":
                        raise TransportError("websocket_subscription_error")
                elif data.get("T") in {"te", "q", "mi"}:
                    await on_message(data, received)
    except TransportError:
        raise
    except (OSError, TimeoutError, ValueError, websockets.exceptions.WebSocketException):
        raise TransportError("websocket_transport_or_protocol_error") from None
