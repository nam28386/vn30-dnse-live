# Executed validation — 2026-11-16

Current-instance results only. No publication, fresh-task restoration, live DNSE connection, trading behavior or empirical market hypothesis has been validated.

| Check actually executed | Result |
|---|---|
| `bash scripts/install.sh` | PASS: frozen uv sync, npm ci, TypeScript check and Vite production build |
| `uv run pytest -q` | 34 passed in 2.17s; no skips or expected failures |
| `uv run ruff check backend scripts` | PASS |
| `uv run ruff format --check backend scripts` | PASS: 20 files formatted |
| `npm --prefix frontend test` | 5 passed, 1 test file, 935ms total runner duration |
| `npm --prefix frontend run build` | PASS: TypeScript + Vite, 1587 modules; also run by install.sh |
| `node frontend/scripts/browser-qa.mjs` | PASS against restarted services, actual system Chromium |
| Backend HTTP `/api/state`, `/api/health` | PASS: MOCK, nonempty history, available VWAP, zero rejected records at check |
| Frontend HTTP | PASS: HTML shell returned by Vite |
| `uv run python scripts/export_mock.py` | PASS: 180 steps, 2 descriptive events, 0 rejected records, 3 hashed raw/Parquet artifacts, provenance manifest |
| `python scripts/check_sdk_contract.py /tmp/dnse-openapi-sdk` | PASS: 13 signatures/defaults verified directly against official source |
| Versioned JSON Schema export | 8 contracts exported to docs/schemas/1.0.0 |

Tests cover schema roundtrips and rejection, non-finite values, MBP ordering, dynamic point-in-time contract selection, every feature formula/warmup, unknown-side quality, stale/delayed inputs, session resets, no future dependencies, prefix stability, no premature/carried-quote markouts, event measurement revision times, impact retention, spread/depth recovery, missing quotes, invalid events, session/gap censoring, duplicate rejection, deterministic replay, raw hashes, DuckDB/Polars Parquet, exact adapter calls, read-only HTTP methods, WebSocket snapshots, fail-closed LIVE mode and nested/inline secret redaction.

UI tests check source/inference labels, missing versus zero values, pending markout display, event details, feature quality, disconnect warnings and loading. They mock charts. Chromium QA exercises actual Lightweight Charts canvases, market-clock updates, CVD/volume switching, event details, feature-quality navigation, 1440×1050 desktop and 390×844 mobile, no horizontal mobile overflow, a forced socket interruption, frozen-data warning, and automatic reconnect. No uncaught browser JavaScript errors were recorded. Chromium's offline emulation alone leaves existing WebSockets active, so QA explicitly closes the routed market socket while offline. This is an injected transport test, not a DNSE outage drill.

Screenshots and machine-readable QA report are local ignored artifacts:

- `artifacts/desktop.png`
- `artifacts/mobile.png`
- `artifacts/events.png`
- `artifacts/browser-qa.json`

The final bounded export is `.data/exports/5e9da34f29e24a8fa80f495bf427d8a1/` in this instance. Its manifest records source/lockfile hashes, package/runtime versions, nullable Git revision (repository has no commits), fixture parameters, artifact hashes and explicitly synthetic status. Both backend and Vite were restarted and functional requests repeated after installation.

One dependency warning remains: the installed Starlette TestClient deprecates the httpx integration in favor of httpx2. All integration tests executed successfully; it is not suppressed. Installation also reports the transitive whatwg-encoding deprecation. Neither is presented as a failing test.

## Limitations and next validation

- Official docs website returned HTTP 403; current SDK/spec were inspected via GitHub. No live response-body or session/side mappings are claimed.
- SDK REST hostname checking needs a verified correction before live use. No TLS bypass was introduced or used.
- MOCK uses a synthetic continuous session and an accelerated logical clock. Production calendar, expiry cutoff, live normalizers, entitlement checks, pagination traversal, raw frame capture and end-to-end DNSE reconnect need the separate work listed in DNSE.md.
- Journals use one local process. There is no multi-user deployment, network authentication, tamper-proof archive, or restart recovery of in-memory state. New process = new replay run; old journals are retained.
- Software readiness is demonstrated for MOCK development. Predictive/causal/economic validity is unassessed; no ML, backtest, order or automated signal code exists.
- Reusable `install_script` and `start_skill` were confirmed saved to the environment draft. This does not execute or publish them; review/save in environment settings and publish to activate the prepared environment. Restoration in a new task is untested.
