"""Unauthenticated, read-only transport diagnostics for documented DNSE hosts.

This direct-socket checker is deliberately independent of SDK authentication. It
never reads credential values into the request, follows redirects, or reads bodies.
"""

import http.client
import os
import queue
import socket
import ssl
import threading
from dataclasses import asdict, dataclass

HOSTS = {
    "production": {"rest": "openapi.dnse.com.vn", "websocket": "ws-openapi.dnse.com.vn"},
    "sandbox": {"rest": "sb-openapi.dnse.com.vn", "websocket": "ws-sb-openapi.dnse.com.vn"},
}


@dataclass(frozen=True)
class Result:
    status: str
    reason: str


def required_context():
    """Always verify CA chain and DNS name. Never honor a caller-supplied context."""
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError("TLS verification unavailable")
    return context


def verify_tls(sock, hostname):
    return required_context().wrap_socket(sock, server_hostname=hostname)


def credentials_status(environ=None):
    env = os.environ if environ is None else environ
    present = bool(env.get("DNSE_API_KEY")) and bool(env.get("DNSE_API_SECRET"))
    return Result("UNKNOWN", "not_tested" if present else "missing_credentials")


def classify_authenticated_http(status):
    """Classify a future isolated HTTP response. Does not perform authentication."""
    if status in (401, 403):
        return Result("FAIL", "authentication_or_authorization_rejected"), Result("UNKNOWN", "not_tested")
    if 200 <= status < 300:
        return Result("PASS", "authenticated_http_accepted"), Result("UNKNOWN", "payload_not_validated")
    return Result("UNKNOWN", "authentication_not_established"), Result("FAIL", "market_data_http_error")


def classify_market_data(valid):
    return Result("PASS", "payload_validated") if valid else Result("FAIL", "invalid_market_data")


def _resolve(hostname, timeout):
    result = queue.Queue(maxsize=1)

    def lookup():
        try:
            result.put((True, socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)))
        except OSError:
            result.put((False, None))

    threading.Thread(target=lookup, daemon=True).start()
    try:
        ok, addresses = result.get(timeout=timeout)
    except queue.Empty:
        return Result("FAIL", "dns_timeout"), []
    if not ok or not addresses:
        return Result("FAIL", "dns_resolution_failed"), []
    return Result("PASS", "resolved"), addresses[:4]


def probe(environment="sandbox", service="rest", timeout=3.0):
    if environment not in HOSTS or service not in HOSTS[environment]:
        raise ValueError("only documented DNSE environments and hosts are supported")
    if not 0 < timeout <= 10:
        raise ValueError("timeout must be in (0, 10]")
    host = HOSTS[environment][service]
    result = {
        "environment": environment,
        "service": service,
        "host": host,
        "route": "direct_no_proxy",
        "dns": Result("UNKNOWN", "not_attempted"),
        "tcp": Result("UNKNOWN", "not_attempted"),
        "tls": Result("UNKNOWN", "not_attempted"),
        "http": Result("UNKNOWN", "not_attempted"),
        "authentication": credentials_status(),
        "market_data": Result("UNKNOWN", "not_attempted"),
    }
    result["dns"], addresses = _resolve(host, timeout)
    if not addresses:
        return serialize(result)
    sock = None
    failure = "connection_failed"
    for family, socktype, protocol, _, address in addresses:
        candidate = None
        try:
            candidate = socket.socket(family, socktype, protocol)
            candidate.settimeout(timeout)
            candidate.connect(address)
            sock = candidate
            break
        except PermissionError:
            failure = "network_access_denied"
            if candidate is not None:
                candidate.close()
        except (socket.timeout, TimeoutError):
            failure = "tcp_timeout"
            if candidate is not None:
                candidate.close()
        except OSError:
            if candidate is not None:
                candidate.close()
    if sock is None:
        result["tcp"] = Result("FAIL", failure)
        return serialize(result)
    result["tcp"] = Result("PASS", "connected")
    try:
        try:
            with verify_tls(sock, host) as secure:
                result["tls"] = Result("PASS", "trusted_chain_and_hostname")
                # HEAD is unauthenticated and has no request body or redirect following.
                secure.sendall(
                    f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("ascii")
                )
                response = http.client.HTTPResponse(secure)
                response.begin()
                code = response.status
                result["http"] = Result("PASS" if 100 <= code < 500 else "FAIL", f"http_{code}")
        except ssl.SSLCertVerificationError:
            result["tls"] = Result("FAIL", "certificate_or_hostname_verification_failed")
        except ssl.SSLError:
            if result["tls"].status == "PASS":
                result["http"] = Result("FAIL", "http_tls_error")
            else:
                result["tls"] = Result("FAIL", "tls_handshake_failed")
        except (socket.timeout, TimeoutError):
            stage = "http" if result["tls"].status == "PASS" else "tls"
            result[stage] = Result("FAIL", f"{stage}_timeout")
        except (OSError, http.client.HTTPException):
            stage = "http" if result["tls"].status == "PASS" else "tls"
            result[stage] = Result("FAIL", f"{stage}_connection_failed")
    finally:
        sock.close()
    return serialize(result)


def serialize(results):
    return {key: asdict(value) if isinstance(value, Result) else value for key, value in results.items()}
