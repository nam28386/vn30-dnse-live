# DNSE security audit and connectivity checklist

Audit date: 2026-11-16. Reference: official `dnse-tech/openapi-sdk` at commit `aa55a5117de2534707bca6165b6738e1cc6fc6a4`, `python/README.md`, `python/dnse/api/client.py`, `python/dnse/api/common.py`, `python/dnse/websocket/{client,connection}.py`, and `spec/dnse-openapi-2026-09-15.yaml`. The rendered DNSE documentation host was not reachable in this environment. No authenticated requests were sent.

## Source findings and compatibility

| Finding | Evidence | Disposition |
|---|---|---|
| REST hostname check disabled | Official `DNSEClient.__init__` passes `assert_hostname=False` to `urllib3.PoolManager`. The source has a commented-out certificate-disable line; that comment is not an active setting. The SDK's actual certificate-chain behavior depends on its urllib3/runtime configuration; it was not independently tested against DNSE. | The existing market-data facade rejects direct official SDK REST client instances and subclasses. Our unauthenticated checker independently uses Python's default trust store, verifies CA chain **and** expected hostname, and fails closed if either setting is not enabled. This does not repair the SDK's REST transport. |
| REST debug/dry-run leaks | SDK `_request` prints `req_headers` whenever `DEBUG=true` **or** `dry_run=True`; this includes the API key and signed authorization material. The SDK `common.send_signed_request` also prints headers when debug is enabled. | Never call the SDK REST client's debug/dry-run paths with credentials. The direct SDK REST client is blocked by the facade. The checker never uses that client, reads no credentials into HTTP, never logs headers/bodies/exceptions, and has no authenticated or dry-run mode. |
| WebSocket logging | SDK WebSocket code creates its own handlers, logs session identifiers, untrusted server error text, subscriptions, and exception strings. Disabling only the `dnse` parent logger does not reliably disable children with their own handlers. | The market-data stream facade rejects direct SDK WebSocket clients and subclasses pending a safe logging integration. Already-created SDK child loggers are suppressed by our logging configuration as defense in depth, not as a substitute for the facade block. |
| WebSocket TLS | The inspected SDK creates a verified default SSL context with certifi. Lines showing disabled verification are comments, not active assignments. | Not validated by a real DNSE handshake. The checker tests DNS/TCP/TLS plus an unauthenticated HTTPS HEAD only; it does **not** perform a WebSocket upgrade. |
| Official environment naming differs | SDK README distinguishes production and sandbox hosts, while the included OpenAPI spec lists an `openapi-uat` server and one SDK example references a `ws-openapi-uat` host. | Treat UAT as a distinct unresolved environment; do not assume it is an alias for sandbox. Confirm entitlements and exact UAT endpoints with DNSE before use. |

The API contract source lists the following production and sandbox hosts (HTTPS/WSS, port 443). Production and sandbox use separate credentials, per the SDK README.

| Environment | REST | WebSocket |
|---|---|---|
| Production | `openapi.dnse.com.vn` | `ws-openapi.dnse.com.vn` |
| Sandbox | `sb-openapi.dnse.com.vn` | `ws-sb-openapi.dnse.com.vn` |

For rendered documentation, `developers.dnse.com.vn` is a separate host. The spec names `openapi-uat.dnse.com.vn`, and an example names `ws-openapi-uat.dnse.com.vn`; neither is included as an assumed sandbox destination in the checker. API versions in the SDK README are `2026-07-23` for production and sandbox; the OpenAPI document version `1.0.0` and SDK module version `1.0.0` are separate. Server acceptance is unverified.

## Checker and trust boundaries

Run from the repository root:

```bash
UV_CACHE_DIR=/workspace/.cache/uv uv run python scripts/check_dnse_connectivity.py --environment sandbox --service all --timeout 3
```

`--environment production` is an **unauthenticated transport probe**; no authenticated production requests are possible through this checker. `--service` is `rest`, `websocket` or `all`. The checker uses a fixed official host allowlist, bounded DNS/TCP/TLS/HTTP operations and HTTPS HEAD `/` with no query, headers containing credentials, redirects, or response body retention. It uses direct sockets, not the environment's HTTP or WSS proxy; DNS/TCP failures do not prove the service is down or its proxied route is unusable. Connect timeout is per address (up to four); DNS is bounded separately. It emits fixed categories and HTTP status only; it does not include exception text, addresses, credential values, response bodies, certificates, session IDs, or market data. It returns zero only when every selected host's TLS and HTTP transport probes pass.

`dns`, `tcp`, `tls` and `http` are separate. HTTP `PASS` with a 4xx response means an HTTP server responded; it is not service, entitlement or authentication success. The `authentication` status checks only credential variable presence and stays UNKNOWN even when they exist. `market_data` always stays UNKNOWN. The pure response-classification helpers distinguish 401/403, other HTTP errors and invalid market data for future integration; they do not make a request or verify credentials. The checker does not implement a live authenticated market-data test; adding one requires a separately audited verified client and transport. No market-data payload is persisted.

The redacting JSON formatter masks sensitive structured fields, common key/value formats and exact values present in the named DNSE credential environment variables. It is defense in depth: secret-free diagnostics require the stronger rule that code never logs headers, credentials, signatures, response bodies, arbitrary exception text or SDK output. Arbitrary external libraries and custom injected client implementations are outside that formatter's guarantee. The facade restriction detects direct SDK classes through their class ancestry; an arbitrary third-party wrapper can bypass that check and must not be treated as a hardened client. The application continues to reject LIVE mode.

## Results actually observed

- `scripts/check_dnse_connectivity.py --environment sandbox --timeout 2`: sandbox REST DNS returned `dns_resolution_failed`; WebSocket-host DNS returned `dns_timeout`; exit status 1. Remaining transport, authentication and data stages are UNKNOWN. The current enforced restricted network policy has no DNSE hosts in its effective allowlist. Direct-route results do not establish proxied reachability.
- Local TLS tests start a loopback server with a newly generated synthetic certificate. A trusted matching hostname succeeds; an untrusted certificate and a trusted certificate with the wrong hostname both fail. These are local verification tests, not DNSE connectivity tests.
- Backend tests also exercise missing credentials, direct network permission denial, DNS/TCP/HTTP timeouts, safe error reporting, synthetic 401/403 classification, invalid market-data classification, SDK facade blocking and nested/unstructured redaction. Authentication failure is a synthetic classification test, not a real failed login.
- Refer to the task response for the final test counts; no live market data has been fetched or stored.

## Connectivity checklist

- [x] Identify official production and sandbox hostnames and SDK version/header documentation.
- [x] Use trusted-chain and hostname verification in the unauthenticated checker; test bad certificate and wrong hostname on loopback.
- [x] Block direct unmodified SDK REST/WebSocket clients at the market-data facades; keep LIVE disabled.
- [x] Test redaction and fixed diagnostic outputs without real credentials.
- [x] Run bounded unauthenticated sandbox diagnostics; report unavailable stages accurately.
- [ ] Establish the permitted HTTPS/WSS proxy route and allow the appropriate official destinations, as needed for the selected environment.
- [ ] Clarify UAT versus sandbox endpoints, credential scope, TLS interception/trust store and market-data retention terms with authoritative DNSE documentation.
- [ ] Implement and independently test a read-only SDK-compatible REST transport that verifies the chain and hostname and prevents SDK stdout/debug/dry-run and untrusted logging leaks. Do not reuse the unhardened injected SDK client.
- [ ] Implement a similarly controlled WebSocket logging/authentication boundary, with reconnect and resubscription tests.
- [ ] Once sandbox access is authorized and configured, run a bounded authenticated sandbox market-data test with credential values only in memory, category-only diagnostics, and no persisted market payloads unless licensed. Do not claim a 401/403 or empty payload as success.
- [ ] Keep authenticated production requests disabled until separately authorized and all preceding checks pass.
