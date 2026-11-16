import asyncio
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from vn30.adapters.secure_dnse import TransportError
from vn30.diagnostics import ObservingREST, stream_summary, summary


def test_endpoint_summaries_exclude_unrecognized_and_sensitive_fields():
    result = summary(
        "trades",
        {
            "trades": [
                {
                    "symbol": "SYNTHETICF",
                    "time": "2026-01-05 09:00:00.123",
                    "matchPrice": 100,
                    "matchQtty": 2,
                    "apiKey": "SECRET_MARKER",
                    "accountNo": "ACCOUNT_MARKER",
                }
            ]
        },
    )
    assert result["record_count"] == 1
    assert result["timestamp"] == "2026-01-05T02:00:00.123000+00:00"
    assert result["fields"] == ["matchPrice", "matchQtty", "symbol", "time"]
    assert "SECRET_MARKER" not in str(result) and "accountNo" not in str(result)
    assert summary("quotes", {"quotes": []})["schema"] == "EMPTY"
    assert summary("quotes", {"quotes": "wrong"})["schema"] == "INVALID"


def test_observer_records_http_status_and_safe_auth_error():
    class Fail:
        def get(self, *args, **kwargs):
            raise TransportError("authentication_or_authorization_rejected", http_status=401)

    observer = ObservingREST(Fail())
    with pytest.raises(TransportError):
        observer.get("instruments")
    assert observer.observations == [
        {
            "endpoint": "/market/instruments",
            "http_status": 401,
            "result": "authentication_or_authorization_rejected",
        }
    ]


def test_stream_summary_reports_only_verified_market_fields():
    now = datetime.now(timezone.utc)
    payload = {
        "T": "q",
        "symbol": "SYNTHETICF",
        "time": (now - timedelta(seconds=1)).isoformat(),
        "bid": [{"price": 100, "qtty": 2}],
        "offer": [{"price": 101, "qtty": 4}],
        "signature": "SECRET_MARKER",
    }
    result = stream_summary(payload, now)
    assert result["channel"] == "Quotes" and result["best_bid"] == 100 and result["best_ask"] == 101
    assert result["bid_levels"] == result["ask_levels"] == 1 and result["freshness_seconds"] == 1
    assert "SECRET_MARKER" not in str(result) and "signature" not in str(result)


def test_rest_success_survives_websocket_network_failure(monkeypatch, capsys):
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/dnse_local_check.py"))
    main = module["main"]
    env = main.__globals__
    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")

    async def rest_ok():
        pass

    async def ws_blocked():
        raise TransportError("network_blocked")

    class FakeREST:
        def __init__(self, credentials, *, authorized):
            assert authorized
            self.last_http_status = 200

        def get(self, operation, *, symbol=None, query=None):
            now = datetime.now(timezone.utc)
            if operation == "instruments":
                return {
                    "data": [
                        {
                            "symbol": "SYNTHETICF",
                            "symbolType": "VN30F1M",
                            "marketId": "DVX",
                            "securityGroupId": "FU",
                        }
                    ],
                    "total": 1,
                }
            if operation == "security_definition":
                return [
                    {
                        "symbol": symbol,
                        "productGrpId": "FIO",
                        "finalTradeDate": (now + timedelta(days=7)).date().isoformat(),
                        "boardId": "G1",
                        "securityStatus": "NO_HALT",
                    }
                ]
            if operation == "ohlc":
                return {
                    "t": [int(now.timestamp()) - 60],
                    "o": [100],
                    "h": [102],
                    "l": [99],
                    "c": [101],
                    "v": [4],
                }
            return {"trades": [], "quotes": []} if operation in {"trades", "quotes"} else []

    monkeypatch.setitem(env, "preflight_rest", rest_ok)
    monkeypatch.setitem(env, "preflight_ws", ws_blocked)
    monkeypatch.setitem(env, "SecureREST", FakeREST)
    assert asyncio.run(main()) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["network"] == {"rest": "PASS", "websocket": "FAIL"}
    assert data["authentication"] == "PASS" and data["rest_market"] == "REST_LIVE_VERIFIED"
    assert data["websocket"] == "UNKNOWN" and data["websocket_error"] == "network_blocked"
    assert data["contract"] == "SYNTHETICF"
    assert data["endpoints"][0]["http_status"] == 200 and data["endpoints"][0]["record_count"] == 1
    assert "SYNTHETIC_SECRET" not in output and "SYNTHETIC_KEY" not in output


def test_unexpected_error_never_prints_exception_text(monkeypatch, capsys):
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/dnse_local_check.py"))
    main = module["main"]
    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")

    async def unexpected():
        raise RuntimeError("UNTRUSTED_SERVER_CONTENT SYNTHETIC_SECRET")

    monkeypatch.setitem(main.__globals__, "preflight_rest", unexpected)
    assert asyncio.run(main()) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error"] == "internal_error"
    assert "UNTRUSTED_SERVER_CONTENT" not in output and "SYNTHETIC_SECRET" not in output
