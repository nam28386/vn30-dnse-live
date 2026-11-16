import asyncio
import json

import pytest
from vn30.adapters.secure_dnse import (
    API_VERSION,
    Credentials,
    SecureREST,
    SecureStream,
    TransportError,
    read_only_path,
    rest_headers,
    ws_auth,
)


@pytest.fixture
def credentials():
    return Credentials("SYNTHETIC_KEY", "SYNTHETIC_SECRET")


# Expected vectors were generated using the official SDK at commit
# aa55a5117de2534707bca6165b6738e1cc6fc6a4 with exclusively synthetic keys.
def test_signing_matches_official_sdk_vector(credentials):
    date, nonce, endpoint = "Mon, 16 Nov 2026 06:00:00 +0000", "synthetic_nonce", "/market/instruments"
    headers = rest_headers(credentials, endpoint, date, nonce)
    assert (
        headers["X-Signature"]
        == 'Signature keyId="SYNTHETIC_KEY",algorithm="hmac-sha256",headers="(request-target) date",signature="nQRQAoWlLFStwfHtCQkVeFJWqNRfpgf8ftygNP7c7G0%3D",nonce="synthetic_nonce"'
    )
    assert headers["version"] == API_VERSION


def test_websocket_auth_matches_official_sdk_vector(credentials):
    assert (
        ws_auth(credentials, 1234567890, "123456")["signature"]
        == "2e5796606eada352ff4a2e3427b52e6079ff3bb894259fc1ef5c072429fba8c6"
    )


def test_credentials_come_from_environment_and_repr_is_safe(monkeypatch):
    monkeypatch.delenv("DNSE_API_KEY", raising=False)
    monkeypatch.delenv("DNSE_API_SECRET", raising=False)
    with pytest.raises(TransportError, match="missing_credentials"):
        Credentials.from_environment()
    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")
    c = Credentials.from_environment()
    assert "SYNTHETIC" not in repr(c)


def test_allowlist_rejects_order_and_path_traversal():
    assert read_only_path("instruments") == "/market/instruments"
    assert read_only_path("security_definition", "SYNTHETIC") == "/price/SYNTHETIC/secdef"
    for operation, symbol in [("orders", None), ("quotes", "../orders"), ("quotes", ".."), ("cancel", "X")]:
        with pytest.raises(ValueError):
            read_only_path(operation, symbol)


def test_rest_uses_verified_context_fixed_host_get_and_no_debug_output(credentials, monkeypatch, capsys):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setattr("vn30.adapters.secure_dnse._AUTHENTICATED_IO_ENABLED", True)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return b'{"data": []}'

    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            assert request.full_url.startswith("https://openapi.dnse.com.vn/market/instruments?")
            assert timeout <= 10
            return Response()

    client = SecureREST(credentials)
    client._opener = Opener()
    assert client.get("instruments", query={"marketId": "DVX", "securityGroupId": "FU"}) == {"data": []}
    output = capsys.readouterr()
    assert "SYNTHETIC" not in output.out + output.err


def test_rest_does_not_follow_redirects_or_echo_errors(credentials, monkeypatch):
    monkeypatch.setattr("vn30.adapters.secure_dnse._AUTHENTICATED_IO_ENABLED", True)
    import urllib.error

    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "SYNTHETIC_SECRET", {}, None)

    client = SecureREST(credentials)
    client._opener = Opener()
    with pytest.raises(TransportError, match="authentication_or_authorization_rejected") as exc:
        client.get("instruments")
    assert "SYNTHETIC" not in str(exc.value)
    with pytest.raises(ValueError):
        client.get("orders")


def test_websocket_is_bounded_and_never_logs_auth(credentials, monkeypatch, capsys):
    monkeypatch.setattr("vn30.adapters.secure_dnse._AUTHENTICATED_IO_ENABLED", True)
    sent = []

    class Socket:
        def __init__(self):
            self.messages = iter(
                [
                    json.dumps({"sid": "synthetic_session"}),
                    json.dumps({"action": "auth_success"}),
                    json.dumps({"T": "q", "symbol": "SYNTHETIC"}),
                ]
            )

        async def recv(self):
            return next(self.messages)

        async def send(self, data):
            sent.append(json.loads(data))

    class Connection:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            pass

    def connect(url, **kwargs):
        assert url.startswith("wss://ws-openapi.dnse.com.vn/")
        assert kwargs["ssl"].check_hostname
        assert kwargs["logger"].disabled
        return Connection()

    monkeypatch.setattr("vn30.adapters.secure_dnse.websockets.connect", connect)
    result = asyncio.run(SecureStream(credentials).sample("SYNTHETIC", "G1", duration=1, max_messages=1))
    assert result == [{"T": "q", "symbol": "SYNTHETIC"}]
    assert sent[0]["action"] == "auth"
    assert all(item["action"] == "subscribe" and len(item["channels"]) == 1 for item in sent[1:])
    assert len(sent) == 4
    output = capsys.readouterr()
    assert "SYNTHETIC_SECRET" not in output.out + output.err
    assert "SYNTHETIC_KEY" not in output.out + output.err


def test_production_authentication_fails_closed_by_default(credentials):
    with pytest.raises(TransportError, match="security_gate_not_approved"):
        SecureREST(credentials).get("instruments")
    with pytest.raises(TransportError, match="security_gate_not_approved"):
        asyncio.run(SecureStream(credentials).sample("SYNTHETIC", "G1"))


def test_secure_rest_real_tls_rejects_untrusted_cert_and_wrong_hostname(tmp_path, monkeypatch, credentials):
    import http.server
    import ssl
    import subprocess
    import threading

    import vn30.adapters.secure_dnse as secure

    key, cert = tmp_path / "test-key.pem", tmp_path / "test-cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[]}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 2
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert, key)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(secure, "_AUTHENTICATED_IO_ENABLED", True)
    monkeypatch.setattr(secure, "REST_HOST", f"https://127.0.0.1:{server.server_port}")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    try:
        # Both calls use the real HTTPSHandler; neither failed handshake sends HTTP headers.
        monkeypatch.setattr(secure, "required_context", ssl.create_default_context)
        with pytest.raises(TransportError, match="network_or_tls_error"):
            SecureREST(credentials, timeout=2).get("instruments")
        monkeypatch.setattr(secure, "required_context", lambda: ssl.create_default_context(cafile=str(cert)))
        with pytest.raises(TransportError, match="network_or_tls_error"):
            SecureREST(credentials, timeout=2).get("instruments")
        monkeypatch.setattr(secure, "REST_HOST", f"https://localhost:{server.server_port}")
        assert SecureREST(credentials, timeout=2).get("instruments") == {"data": []}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_persistent_stream_auth_ping_and_market_frame_are_bounded_and_private(
    credentials, monkeypatch, capsys
):
    from vn30.adapters.secure_dnse import stream_market

    sent, observed = [], []

    class Socket:
        def __init__(self):
            self.control = iter(
                [json.dumps({"sid": "SYNTHETIC_SESSION"}), json.dumps({"action": "auth_success"})]
            )
            self.frames = iter(
                [
                    json.dumps({"action": "ping"}),
                    json.dumps({"action": "subscribed"}),
                    json.dumps({"action": "error", "channel": "market_index.VN30.json"}),
                    json.dumps({"T": "q", "symbol": "SYNTHETICF"}),
                ]
            )

        async def recv(self):
            return next(self.control)

        async def send(self, data):
            sent.append(json.loads(data))

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.frames)
            except StopIteration:
                raise StopAsyncIteration from None

    class Connection:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("vn30.adapters.secure_dnse.websockets.connect", lambda *args, **kwargs: Connection())

    async def connected():
        observed.append("connected")

    async def message(data, received):
        observed.append((data["T"], received.tzinfo is not None))

    asyncio.run(stream_market(credentials, "SYNTHETICF", "G1", connected, message))
    assert observed == ["connected", ("q", True)]
    assert sent[-1] == {"action": "pong"}
    assert len([x for x in sent if x["action"] == "subscribe"]) == 3
    output = capsys.readouterr()
    assert "SYNTHETIC_KEY" not in output.out + output.err
    assert "SYNTHETIC_SECRET" not in output.out + output.err


def test_websocket_auth_success_remains_observable_if_subscription_fails(credentials, monkeypatch):
    monkeypatch.setattr("vn30.adapters.secure_dnse._AUTHENTICATED_IO_ENABLED", True)
    marked = []

    class Socket:
        def __init__(self):
            self.items = iter(
                [
                    json.dumps({"sid": "SYNTHETIC_SESSION"}),
                    json.dumps({"action": "auth_success"}),
                    json.dumps({"action": "error", "channel": "top_price.G1.json"}),
                ]
            )

        async def recv(self):
            return next(self.items)

        async def send(self, data):
            pass

    class Connection:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("vn30.adapters.secure_dnse.websockets.connect", lambda *args, **kwargs: Connection())
    with pytest.raises(TransportError, match="websocket_subscription_error"):
        asyncio.run(
            SecureStream(credentials).sample("SYNTHETICF", "G1", on_authenticated=lambda: marked.append(True))
        )
    assert marked == [True]


def test_sample_observes_market_message_at_receive_time(credentials, monkeypatch):
    from datetime import datetime, timezone

    class Socket:
        def __init__(self):
            self.items = iter(
                [
                    json.dumps({"sid": "SYNTHETIC_SESSION"}),
                    json.dumps({"action": "auth_success"}),
                    json.dumps({"T": "q", "symbol": "SYNTHETICF"}),
                ]
            )

        async def recv(self):
            return next(self.items)

        async def send(self, data):
            pass

    class Connection:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("vn30.adapters.secure_dnse.websockets.connect", lambda *args, **kwargs: Connection())
    seen = []

    async def observe(data, received):
        seen.append((data["T"], received))

    before = datetime.now(timezone.utc)
    asyncio.run(
        SecureStream(credentials, authorized=True).sample(
            "SYNTHETICF", "G1", max_messages=1, on_message=observe
        )
    )
    after = datetime.now(timezone.utc)
    assert len(seen) == 1 and seen[0][0] == "q" and before <= seen[0][1] <= after
