# DNSE read-only connectivity smoke diagnostics

Recorded 2026-11-16 at approximately 06:40 UTC. This report contains only configuration presence, public documentation findings and diagnostic status. No credentials, signed requests, live market payloads or account data were captured. MOCK remains the application mode.

| Test | Status | Evidence and scope |
|---|---|---|
| Official SDK source | PASS | GitHub HEAD was read successfully and matches inspected commit `aa55a5117de2534707bca6165b6738e1cc6fc6a4`. Its REST and WebSocket SDK modules report version `1.0.0`; 13 facade method signatures match offline. The SDK is not installed as a project dependency. |
| Current rendered documentation | PARTIAL | HTTPS HEAD to the documentation host failed with curl HTTP `000`. The checked-in OpenAPI spec `dnse-openapi-2026-09-15.yaml` at the official SDK HEAD was inspected instead. It reports OpenAPI document version `1.0.0`. No assertion is made about newer rendered documentation. |
| Configured environment and API version | PARTIAL | `DNSE_API_KEY`, `DNSE_API_SECRET`, `DNSE_API_VERSION`, `DNSE_BASE_URL`, `DNSE_WS_BASE_URL` and `VN30_MODE` were absent/empty by presence-only checks. SDK documentation names the first three variables. With no version override, the inspected SDK source would default the request `version` header to `2026-07-23`; the server's accepted version and UAT versus production environment are UNKNOWN. The spec's document version and SDK package version are separate from the request header. |
| Credentials | FAIL | The current runtime has no `DNSE_API_KEY` or `DNSE_API_SECRET`, and environment status reports no configured secret/runtime bindings. No values were requested or printed. |
| Network prerequisites | FAIL | Enforced restricted policy does not include `developers.dnse.com.vn`, `openapi.dnse.com.vn`, or `ws-openapi.dnse.com.vn`. Non-authenticated HTTPS HEAD checks on those hosts returned curl HTTP `000` (connection failed); no HTTP status or remote authentication outcome was observed. |
| Futures instrument query (`marketId=DVX`, `securityGroupId=FU`) | UNKNOWN | Not attempted: credentials and network prerequisites unavailable. The bundled specification defines DVX as derivatives and FU as futures. |
| Identify VN30 front month | UNKNOWN | No instrument response received. The specification documents `symbolType=VN30F1M` as the one-month VN30 futures category; the actual active contract, listing/expiry, cutoff, and how `VN30F1M` maps to an executable month remain unverified. No symbol is hard-coded. |
| Instrument metadata / security definition | UNKNOWN | Not attempted; no contract and no authenticated connection. |
| Trading session | UNKNOWN | Not attempted. The bundled specification identifies `FIO` as the index-futures product group; the actual board, current phase and status remain unverified. |
| Bounded OHLC history | UNKNOWN | Not attempted. The spec lists `type=DERIVATIVE`, OHLC arrays and Unix-second candle timestamps; there was no live sample. |
| Bounded trade pagination | UNKNOWN | Not attempted. Authorized read-only scope was given, but access prerequisites were unavailable. |
| Bounded quote pagination | UNKNOWN | Not attempted for the same reasons. |
| Bounded WebSocket authentication and subscriptions | UNKNOWN | Not attempted. HTTPS HEAD to the WSS host did not establish WebSocket connectivity. No subscription, handshake or message was received. |
| Live message structure / clock precision / depth / freshness | UNKNOWN | No live messages or market data were observed. Public specification descriptions are summarized below solely as documentation, not measurements. |
| Real market-data retention permission | UNKNOWN | No DNSE license or retention terms were established. No real market data was fetched or persisted. |

## What the bundled specification describes

The instruments response has a `data` array and `total`, `page`, `pageSize` fields. OHLC responses have arrays `t`, `o`, `h`, `l`, `c`, `v` and `nextTime`; `t` is described in Unix seconds. Trade and quote history responses have `trades` or `quotes` arrays and `nextPageToken`; a missing or empty token denotes the end. History examples describe trade/quote times as `YYYY-MM-DD HH:mm:ss.SSS` in GMT+7. Quotes contain aggregated `bid` and `offer` price/quantity arrays; the example shows three levels, which does not establish a maximum, a live depth, or order-level data. The trade history description labels BUY/SELL as active side, but vendor origin and exchange-confirmed aggressor identity remain unverified. WebSocket SDK models include optional source time and receive time, but live precision, ordering, gaps and freshness are unknown.

## Preconditions for a later retry

1. Set up the required DNSE market-data credentials through secure environment variables and configure the appropriate UAT or production endpoint. Never put credential values in chat, files, logs or command arguments. No credential value is requested here.
2. Allow the relevant official REST and WebSocket hosts through the environment network policy; allow the documentation host if rendered docs are needed. The environment currently uses restricted networking. Verify that the supported route works for HTTPS **and** WSS; a proxy-supplied placeholder is not automatically suitable for the SDK's local HMAC signing.
3. Before constructing a live REST client, address the inspected SDK's `assert_hostname=False` using a validated fix or audited transport override that preserves CA and hostname verification. The SDK also prints signed headers and the API key when `DEBUG=true` **or** `dry_run=True`: a smoke test must explicitly prevent both paths and suppress SDK transport/session logs. The SDK was not instantiated here.
4. Once authorized access and retention terms are established, call only the documented market-data methods with bounded pagination/timeouts, keep response bodies in memory, summarize field types/precision/depth/freshness without storing market values, and stop on errors. Report actual HTTP/auth/stream outcomes and do not mark empty or unobserved messages as passes.

The offline facade signature check is not a live integration test. See [DNSE.md](DNSE.md) for remaining mappings, source provenance and live handoff.
