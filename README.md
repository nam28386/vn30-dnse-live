# VN30-DNSE-Live-Intelligence v0.1

A read-only, event-driven personal market research workstation. LIVE cục bộ đã có đường thử nhưng chưa được xác minh với DNSE thật; hướng dẫn: [LOCAL_RUN_VI.md](LOCAL_RUN_VI.md). Synthetic VN30 futures observations flow through the same timestamped contracts, incremental features, event lifecycle and storage boundaries intended for future verified market-data ingestion. No real orders, account routes, ML, backtesting, or automated signals; LIVE credentials stay in the backend environment.

## Chạy trên máy cá nhân

Yêu cầu Python 3.11+, uv, Node.js 22+ và npm. Trong thư mục chứa `pyproject.toml`, chạy một lệnh:

```powershell
.\scripts\start_mock.ps1
```

Trên WSL/Linux: `bash scripts/start_mock.sh`. Chế độ LIVE read-only: `.\scripts\start_live.ps1` hoặc `bash scripts/start_live.sh`. Các script chạy backend và frontend trên `127.0.0.1`; LIVE chưa được xác minh với DNSE thật và không tự chuyển sang MOCK nếu bị chặn.

Mở `http://127.0.0.1:5173`. Xem [LOCAL_RUN_VI.md](LOCAL_RUN_VI.md) để giải nén ZIP, chẩn đoán và cấu hình môi trường. Ứng dụng không tự đọc `.env`; MOCK không cần credentials. Vite chuyển HTTP/WebSocket cùng origin tới backend, không cần CORS.

## Architecture and files

```text
backend/vn30/
  contracts.py          eight versioned Pydantic research schemas, MBP levels, quality
  adapters/mock.py      deterministic synthetic event sequence / fixture clock
  adapters/dnse.py      SDK protocols and read-only facades; direct SDK clients blocked
  connectivity.py       verified unauthenticated DNS/TCP/TLS/HTTP diagnostics
  features.py           arrival-ordered incremental features + public definitions
  events.py             descriptive flow-shock lifecycle, markout/recovery guards
  storage.py            append raw/hash journal, normalized DuckDB, Polars Parquet
  service.py            replay orchestration, rejection handling, reconnect boundary
  logging.py            structured operational logs + recursive secret redaction
  api.py                FastAPI lifespan, GET endpoints, outbound-only market stream
backend/tests/          formula, schema, temporal, event, storage, adapter, API tests
frontend/src/
  App.tsx               responsive workstation, source/health, event and quality views
  Chart.tsx             TradingView Lightweight Charts integration
  types.ts              display contracts and formatting
  style.css             responsive desktop/mobile styling
  App.test.tsx          UI behavior tests
frontend/scripts/browser-qa.mjs   real Chromium functional QA + screenshots
scripts/                frozen install, bounded export, schema export, SDK signature audit
AGENTS.md               coding/research guardrails
.env.example            non-secret mock settings
pyproject.toml / uv.lock          Python dependency contract
frontend/package*.json           frontend dependency contract and lock
```

Data path: raw fixture payload → content hash → normalized versioned record → incremental feature snapshot → descriptive event revisions → read-only API/WebSocket → dashboard. Each input has source event, receive, processing and availability times. Feature decision time is explicit. Late/rejected inputs are auditable and cannot rewrite earlier observations.

## Storage and provenance

Each process or export uses a unique `.data/<run-id>/` directory. `raw/events.jsonl` contains original payloads in hash wrappers; `normalized/market.duckdb` contains separate input, derived-revision and rejection tables. Derived records include input IDs/recursive lineage and raw content references. This is an application append-only journal, not tamper-proof WORM storage. Never journal authentication or private/account traffic. `Journal` currently accepts mock fixture envelopes; live pre-decode framing remains future work.

Graceful shutdown exports normalized and derived Parquet envelopes through Polars; DuckDB/raw are retained during runtime. Abrupt process termination may skip Parquet export; source DuckDB/raw are the retained artifacts. Parquet has typed ID/time/kind columns plus versioned JSON payload, preserving nested schemas without guessing a unified flat vendor schema.

```bash
uv run python scripts/export_mock.py
```

This writes a separate 180-step run with Parquet and a fixture manifest. It is an engineering fixture, not empirical market research. Replay is deterministic; run directory IDs vary. Session fixture is synthetic 2026-01-05; `MOCK-VN30-NEAR/NEXT` are fictional labels, not real contracts. Tick cadence is 10 simulated seconds per 0.8 wall-clock seconds by default. Startup seeds 150 steps so MA21 is observable. The demo does not implement a production exchange calendar or roll schedule.

## Read-only API

- `GET /api/state`: dashboard state, bounded history and recent events
- `GET /api/health`: feed/quality clocks and counters
- `GET /api/instruments`: synthetic point-in-time contract catalog
- `GET /api/features/definitions`: formulas, units, inputs, version, availability
- `GET /api/events`: event revisions currently in memory
- `WS /api/stream`: outbound dashboard snapshots, no client mutation commands
- `/docs` and `/openapi.json`: generated API documentation

GET endpoints do not mutate the research stream. Replay is an independent background task. REST POST/PUT/PATCH/DELETE are unavailable. Research state belongs to a single local development process; network authentication, multi-user access, cross-origin deployment and historical query APIs are outside this slice.

## Validation

```bash
uv run pytest -q
uv run ruff check backend
npm --prefix frontend test
npm --prefix frontend run build
# With backend + Vite running and Chromium installed:
node frontend/scripts/browser-qa.mjs
# Optional independent official SDK checkout (not a runtime dependency):
python scripts/check_sdk_contract.py /tmp/dnse-openapi-sdk
```

For browser QA, system `/usr/bin/chromium` is used when present. Otherwise run `cd frontend && npx playwright install chromium`, or set `CHROMIUM_PATH`. Screenshots/results go to ignored `artifacts/`. Unit UI tests mock chart rendering; browser QA exercises the actual Lightweight Charts canvases. See [validation results](docs/VALIDATION.md) for commands actually executed and limitations.

## Research definitions and live integration

Hướng dẫn khởi động một lệnh và chẩn đoán Windows/WSL/Linux: [LOCAL_RUN_VI.md](LOCAL_RUN_VI.md). Báo cáo kiểm tra Production trước đó: [DNSE_LIVE_STATUS_VI.md](docs/DNSE_LIVE_STATUS_VI.md).

The [security audit and checklist](docs/DNSE_SECURITY_AUDIT.md) documents the unauthenticated connectivity checker and remaining live-client blockers.

The latest read-only connectivity attempt is documented in [redacted smoke diagnostics](docs/DNSE_SMOKE_2026-11-16.md).

Read [feature/event contracts](docs/FEATURES.md) for exact formulas, freshness, completed-bar semantics, quality, recovery definitions and censoring. Read [DNSE audit and live handoff](docs/DNSE.md) for SDK provenance, verified interfaces, outstanding response/side/time/board questions and required live steps. The official docs website returned 403 here. No DNSE live connection has been tested.

MA21 uses 21 completed observed one-minute trade bars (no empty-minute filling), not 21 ticks. CVD is inferred and incomplete when direction is unknown. Markouts need both source and availability time at/after their horizon. All eight JSON Schemas are exported under `docs/schemas/1.0.0/` (`uv run python scripts/export_schemas.py`). Flow-size thresholds are fixture parameters, not validated market signals. Passing software tests does not establish predictive, causal or economic validity.

TradingView Lightweight Charts is Apache-2.0 licensed; chart attribution remains enabled. See [NOTICE](NOTICE).
