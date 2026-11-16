import json
import logging
import socket
import ssl
import subprocess
import threading

import pytest
from vn30 import connectivity
from vn30.adapters.dnse import DNSEReadOnlyREST
from vn30.connectivity import Result, classify_authenticated_http, classify_market_data, credentials_status
from vn30.logging import JSONFormatter


@pytest.fixture(scope="module")
def local_certificate(tmp_path_factory):
    root = tmp_path_factory.mktemp("tls")
    key, cert = root / "key.pem", root / "cert.pem"
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
    return key, cert


def handshake(certificates, hostname, trust, monkeypatch):
    key, cert = certificates
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)

    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                try:
                    with server_context.wrap_socket(conn, server_side=True):
                        pass
                except (ssl.SSLError, OSError):
                    pass
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    context = ssl.create_default_context(cafile=str(cert)) if trust else ssl.create_default_context()
    monkeypatch.setattr(connectivity, "required_context", lambda: context)
    try:
        sock = socket.create_connection(listener.getsockname(), timeout=3)
        try:
            with connectivity.verify_tls(sock, hostname):
                pass
        finally:
            sock.close()
    finally:
        thread.join(timeout=3)


def test_untrusted_server_certificate_fails(local_certificate, monkeypatch):
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(local_certificate, "localhost", False, monkeypatch)


def test_hostname_mismatch_fails_with_trusted_certificate(local_certificate, monkeypatch):
    with pytest.raises(ssl.SSLCertVerificationError, match="Hostname mismatch"):
        handshake(local_certificate, "other.example", True, monkeypatch)


def test_trusted_certificate_and_matching_hostname_succeeds(local_certificate, monkeypatch):
    handshake(local_certificate, "localhost", True, monkeypatch)


def test_required_context_enforces_chain_and_hostname():
    ctx = connectivity.required_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname


def test_credentials_missing_or_present_but_not_authenticated():
    assert credentials_status({}).reason == "missing_credentials"
    assert credentials_status({"DNSE_API_KEY": "a"}).reason == "missing_credentials"
    assert credentials_status({"DNSE_API_KEY": "a", "DNSE_API_SECRET": "b"}) == Result(
        "UNKNOWN", "not_tested"
    )


def test_network_denial_is_separate_from_dns_and_auth(monkeypatch):
    monkeypatch.setattr(
        connectivity, "_resolve", lambda *_: (Result("PASS", "resolved"), [(2, 1, 6, "", ("127.0.0.1", 443))])
    )

    def deny(*args):
        raise PermissionError("private content must not appear")

    monkeypatch.setattr(socket, "socket", deny)
    report = connectivity.probe()
    assert report["dns"]["status"] == "PASS"
    assert report["tcp"] == {"status": "FAIL", "reason": "network_access_denied"}
    assert report["tls"]["status"] == report["authentication"]["status"] == "UNKNOWN"
    assert "private content" not in json.dumps(report)


def test_dns_timeout_is_distinct(monkeypatch):
    def timeout(*args, **kwargs):
        raise socket.gaierror("redact this")

    monkeypatch.setattr(socket, "getaddrinfo", timeout)
    result = connectivity.probe(timeout=0.1)
    assert result["dns"] == {"status": "FAIL", "reason": "dns_resolution_failed"}
    assert result["tcp"]["status"] == "UNKNOWN"
    assert "redact this" not in json.dumps(result)


def test_http_authentication_and_data_statuses_are_separate():
    auth, data = classify_authenticated_http(401)
    assert auth == Result("FAIL", "authentication_or_authorization_rejected")
    assert data.status == "UNKNOWN"
    assert classify_authenticated_http(403)[0].status == "FAIL"
    assert classify_authenticated_http(503)[0].status == "UNKNOWN"
    assert classify_authenticated_http(503)[1].status == "FAIL"
    assert classify_authenticated_http(200)[0].status == "PASS"
    assert classify_authenticated_http(200)[1].status == "UNKNOWN"
    assert classify_market_data(False).status == "FAIL"


def test_tcp_timeout_does_not_leak_exception(monkeypatch):
    monkeypatch.setattr(
        connectivity, "_resolve", lambda *_: (Result("PASS", "resolved"), [(2, 1, 6, "", ("127.0.0.1", 443))])
    )

    class TimeoutSocket:
        def settimeout(self, _):
            pass

        def connect(self, _):
            raise TimeoutError("some-secret")

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *args: TimeoutSocket())
    report = connectivity.probe()
    assert report["tcp"] == {"status": "FAIL", "reason": "tcp_timeout"}
    assert "some-secret" not in json.dumps(report)


def test_official_sdk_cannot_enter_unhardened_facade():
    SDKClient = type("DNSEClient", (), {"__module__": "dnse.api.client"})
    with pytest.raises(RuntimeError, match="blocked"):
        DNSEReadOnlyREST(SDKClient())


def test_secret_redaction_from_nested_structured_logs():
    rec = logging.LogRecord("test", logging.ERROR, __file__, 1, "request rejected", (), None)
    rec.metadata = {
        "api_key": "key_synthetic",
        "api_secret": "secret_synthetic",
        "x-signature": "signature_synthetic",
        "Authorization": "auth_synthetic",
        "trading-token": "trading_synthetic",
        "headers": {"X-API-KEY": "nested_synthetic"},
    }
    out = JSONFormatter().format(rec)
    for marker in (
        "key_synthetic",
        "secret_synthetic",
        "signature_synthetic",
        "auth_synthetic",
        "trading_synthetic",
        "nested_synthetic",
    ):
        assert marker not in out


def test_http_request_timeout_stays_separate_and_redacts(monkeypatch):
    monkeypatch.setattr(
        connectivity,
        "_resolve",
        lambda *_: (
            Result("PASS", "resolved"),
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ),
    )

    class Socket:
        def settimeout(self, timeout):
            pass

        def connect(self, address):
            pass

        def close(self):
            pass

    class Secure:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def sendall(self, payload):
            assert payload.startswith(b"HEAD /")
            assert b"Authorization" not in payload
            raise TimeoutError("token_synthetic")

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(connectivity, "verify_tls", lambda *args: Secure())
    report = connectivity.probe()
    assert report["tls"]["status"] == "PASS"
    assert report["http"] == {"status": "FAIL", "reason": "http_timeout"}
    assert report["authentication"]["status"] == "UNKNOWN"
    assert "token_synthetic" not in json.dumps(report)


def test_tls_certificate_failure_recorded_without_sensitive_error(monkeypatch):
    monkeypatch.setattr(
        connectivity,
        "_resolve",
        lambda *_: (
            Result("PASS", "resolved"),
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ),
    )

    class Socket:
        def settimeout(self, timeout):
            pass

        def connect(self, address):
            pass

        def close(self):
            pass

    def fail(*args):
        raise ssl.SSLCertVerificationError("signature_synthetic")

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(connectivity, "verify_tls", fail)
    report = connectivity.probe()
    assert report["tls"] == {"status": "FAIL", "reason": "certificate_or_hostname_verification_failed"}
    assert "signature_synthetic" not in json.dumps(report)


def test_production_checker_cannot_attempt_authenticated_requests(monkeypatch):
    monkeypatch.setenv("DNSE_API_KEY", "key_synthetic")
    monkeypatch.setenv("DNSE_API_SECRET", "secret_synthetic")
    monkeypatch.setattr(connectivity, "_resolve", lambda *_: (Result("FAIL", "dns_resolution_failed"), []))
    report = connectivity.probe("production", "rest")
    assert report["authentication"] == {"status": "UNKNOWN", "reason": "not_tested"}
    assert "key_synthetic" not in json.dumps(report)
    assert "secret_synthetic" not in json.dumps(report)


def test_sdk_stream_client_is_blocked():
    from vn30.adapters.dnse import DNSEReadOnlyStream

    SDKStream = type("TradingClient", (), {"__module__": "dnse.websocket.client"})
    with pytest.raises(RuntimeError, match="blocked"):
        DNSEReadOnlyStream(SDKStream())


def test_secret_redaction_from_unstructured_message_and_environment(monkeypatch):
    monkeypatch.setenv("DNSE_API_KEY", "key_synthetic")
    monkeypatch.setenv("DNSE_API_SECRET", "secret_synthetic")
    monkeypatch.setenv("DNSE_TRADING_TOKEN", "trade_synthetic")
    msg = (
        "{'x-api-key': 'unknown_key', 'X-Signature': 'unknown_signature', "
        "'Authorization': 'Bearer unknown_auth', 'trading-token': 'unknown_trade'} "
        "other data key_synthetic secret_synthetic trade_synthetic"
    )
    rec = logging.LogRecord("test", logging.ERROR, __file__, 1, msg, (), None)
    rec.metadata = {"key_synthetic": "metadata key scrubbed"}
    out = JSONFormatter().format(rec)
    for marker in (
        "unknown_key",
        "unknown_signature",
        "unknown_auth",
        "unknown_trade",
        "key_synthetic",
        "secret_synthetic",
        "trade_synthetic",
    ):
        assert marker not in out


def test_dns_timeout_is_bounded(monkeypatch):
    event = threading.Event()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: event.wait(0.2))
    try:
        report = connectivity.probe(timeout=0.01)
        assert report["dns"] == {"status": "FAIL", "reason": "dns_timeout"}
        assert report["tcp"]["status"] == "UNKNOWN"
    finally:
        event.set()
