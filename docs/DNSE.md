# DNSE integration audit / live handoff

Inspected 2026-11-16:

- Official SDK: https://github.com/dnse-tech/openapi-sdk at `aa55a5117de2534707bca6165b6738e1cc6fc6a4`.
- Official OpenAPI spec in that checkout: `spec/dnse-openapi-2026-09-15.yaml`.
- https://developers.dnse.com.vn/ returned HTTP 403 in this environment. Its current rendered documentation was **not** verified.
- No DNSE authenticated request, WebSocket authentication, subscription, or live market validation was attempted. No credentials were requested or inspected.

## Verified SDK boundary

`backend/vn30/adapters/dnse.py` defines market-data facades and blocks direct official SDK REST and WebSocket client instances until their transport and logging are hardened. It imports no trading functionality and constructs no client. Raw responses intentionally have no guessed response-body model. Mock events are independent synthetic fixtures, not alleged DNSE wire examples.

| Application facade | Official SDK method / signature source |
|---|---|
| instruments | `DNSEClient.get_instruments(symbol=None, market_id=None, security_group_id=None, index_name=None, limit=None, page=None, version=None, dry_run=False)` |
| security_definition | `get_security_definition(symbol, board_id=None, dry_run=False)` |
| ohlc_history | `get_ohlc(bar_type, query=None, dry_run=False)` |
| trade_history | `get_trades(symbol, board_id=None, from_date=None, to_date=None, limit=None, order=None, next_page_token=None, dry_run=False)` |
| quote_history | `get_quotes(...)` with the same parameters as get_trades |
| trading_session | `get_lastest_session(tsc_prod_grp_id=None, board_id=None, dry_run=False)` — official misspelling |
| trade extra | `TradingClient.subscribe_trade_extra(symbols, on_trade_extra=None, encoding="json", board_id=None)` |
| quotes | `subscribe_quotes(symbols, on_quote=None, encoding="json", board_id=None)` |
| official VN30 | `subscribe_market_index(market_index, on_market_index=None, encoding="json")` |
| estimated VN30 | `subscribe_estimated_market_index(estimated_market_index, on_estimated_market_index=None, encoding="json")` |
| session | `subscribe_session(product_group_id, board_id="*", on_session=None, encoding="json")` |

`python scripts/check_sdk_contract.py /path/to/openapi-sdk` compares our protocol parameters/defaults directly with official Python source via AST. It also covers connect/disconnect (13 methods total). Adapter tests use fake injected clients: these prove delegation, **not DNSE connectivity**.

See [security audit and connectivity checklist](DNSE_SECURITY_AUDIT.md) for current hostnames, checker behavior, tested TLS controls, SDK blocks, and remaining live integration work.

## Outstanding API questions

1. Confirm production entitlements, rate limits, retention, history time units, paging termination and error-body shapes. The facade exposes page/cursor controls without assuming response envelopes.
2. Confirm derivatives market/security/product-group/board identifiers, VN30 underlying association, tick size units, expiry/final-trade-date timezone and trading status codes. The SDK example uses product group FIO; no live mapping is asserted here.
3. Confirm `TradeExtra.side` code meanings and origin. SDK model uses `side: int` but that does not establish confirmed exchange aggressor identity. Preserve raw side; until documented, normalize direction UNKNOWN.
4. Verify timestamp formats, precision, source timezone and `_receivedAt` semantics against recorded wire payloads. Do not synthesize an exchange timestamp from receive time.
5. Confirm quote completeness, ordering, auction/empty-level representation, maximum depth, sequence numbers and loss detection. SDK callback is already decoded and can transform timestamps: add a pre-decode raw frame journal before live normalization.
6. Confirm official vs estimated VN30 publication semantics and subscription entitlements. Never silently substitute estimated VN30 in spot basis.
7. Confirm expiry-day cutoff and exchange calendar before selecting a contract intraday on final-trade day. Current selection is nearest unexpired eligible **known metadata**, not a liquidity-optimal roll policy.
8. The inspected REST SDK sets `assert_hostname=False` in `python/dnse/api/client.py`. Resolve with an upstream fix or an audited, tested transport override retaining CA validation and hostname checking before constructing a live client. Never weaken TLS to work around errors.

## Specific next steps for a separate live-connectivity increment

1. Resolve the above semantics using current official docs/support and a pinned official SDK release/commit. Save sanitized representative payload fixtures with provenance; no authentication frames in journals.
2. Configure market-data-only credentials securely in environment settings, never chat or source. A local HMAC SDK may require securely injected raw secrets; proxy placeholder bindings are not automatically usable for local signing. Audit that route before declaring requirements. MOCK needs no DNSE credentials; the unauthenticated checker tests credential presence, and the log formatter uses configured credential values for in-memory redaction.
3. Permit required destinations `openapi.dnse.com.vn` and `ws-openapi.dnse.com.vn` through supported network settings; confirm WSS/proxy support. `developers.dnse.com.vn` is needed for rendered docs access. No live allowlist changes were made for MOCK.
4. Retrieve all instrument pages, normalize verified security definitions, call `discover_front_contract` at the observation time, and subscribe only to the discovered symbol/board. Keep expiry-day cutoff explicit. Record metadata availability; no hard-coded real futures identifier.
5. Connect the SDK with bounded auto-reconnect; verify heartbeat, reauthentication, resubscription, callback ordering and fresh snapshots after gaps. The facade has the five subscriptions; end-to-end transport recovery is not live-tested.
6. Normalize captured market records into these schemas, preserve wire raw separately, implement deduplication using verified source IDs/sequences, and reconcile snapshots/history without rewriting point-in-time features. Censor open events during gaps; mark incomplete aggregates INVALID.
7. Run read-only sandbox smoke tests, timestamp/price/side mapping checks and an outage recovery drill. Only then add explicit LIVE startup support; leave MOCK default. Do not introduce orders, trading tokens, account routes or automatic signals.
