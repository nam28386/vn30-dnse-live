import asyncio
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from vn30.api import create_app
from vn30.live import LiveService, source_time


class FakeREST:
    def __init__(self, credentials, *, authorized=False):
        assert authorized

    def get(self, operation, *, symbol=None, query=None):
        expiry = (datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date() + timedelta(days=7)).isoformat()
        if operation == "instruments":
            assert query["marketId"] == "DVX" and query["securityGroupId"] == "FU"
            return {
                "data": [
                    {
                        "marketId": "DVX",
                        "securityGroupId": "FU",
                        "symbolType": "VN30F1M",
                        "symbol": "SYNTHETICF",
                    }
                ],
                "total": 1,
            }
        if operation == "security_definition":
            return [
                {
                    "symbol": symbol,
                    "productGrpId": "FIO",
                    "finalTradeDate": expiry,
                    "boardId": "G1",
                    "securityStatus": "NO_HALT",
                }
            ]
        return {"data": []}


async def fake_preflight():
    pass


async def fake_stream(credentials, symbol, board, on_connect, on_message):
    assert symbol == "SYNTHETICF" and board == "G1"
    await on_connect()
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    t = now.isoformat()
    await on_message(
        {
            "T": "q",
            "symbol": symbol,
            "time": t,
            "bid": [{"price": 100, "qtty": 10}],
            "offer": [{"price": 101, "qtty": 20}],
        },
        datetime.now(timezone.utc),
    )
    await on_message(
        {"T": "mi", "indexName": "VN30", "transactTime": t, "valueIndexes": 99}, datetime.now(timezone.utc)
    )
    await on_message(
        {"T": "te", "symbol": symbol, "time": t, "matchPrice": 100.5, "matchQtty": 7, "side": 1},
        datetime.now(timezone.utc),
    )
    await asyncio.sleep(10)


def test_market_timestamp_formats_preserve_timezone():
    a = source_time("2026-01-05 09:00:00.123")
    assert a == datetime.fromisoformat("2026-01-05T02:00:00.123+00:00")
    assert source_time({"Seconds": 1767578400, "Nanos": 123000000}).microsecond == 123000


def test_local_live_pipeline_end_to_end_with_synthetic_data(tmp_path, monkeypatch):
    monkeypatch.setenv("VN30_MODE", "LIVE")
    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")
    service = LiveService(preflight_fn=fake_preflight, rest_factory=FakeREST, stream_fn=fake_stream)
    app = create_app(data_dir=tmp_path, live_factory=lambda: service)
    with TestClient(app) as client:
        for _ in range(100):
            state = client.get("/api/state").json()
            if state["health"]["status"] == "LIVE":
                break
            time.sleep(0.01)
        assert state["mode"] == "LIVE" and state["health"]["status"] == "LIVE"
        assert state["instrument"]["symbol"] == "SYNTHETICF"
        assert state["market"]["best_bid"] == 100 and state["market"]["best_ask"] == 101
        assert state["market"]["index"] == 99
        assert state["snapshot"]["values"]["spread"]["value"] == 1
        assert state["history"][-1]["price"] == 100.5
        assert state["history"][-1]["side"] == "UNKNOWN"
        assert state["snapshot"]["values"]["cvd"]["value"] is None
        assert state["history"][-1]["available_at"] >= state["history"][-1]["time"]
        assert "SYNTHETIC_SECRET" not in str(state)
        assert "SYNTHETIC_KEY" not in str(state)
        assert len(service.raw) == 3
        with client.websocket_connect("/api/stream") as ws:
            assert ws.receive_json()["market"]["best_bid"] == 100
        assert client.post("/api/orders").status_code == 404
    assert not list(tmp_path.iterdir())


def test_missing_quotes_staleness_and_disconnect_never_becomes_mock():
    service = LiveService()
    service.contract = (datetime.now(timezone.utc).date(), "SYNTHETICF", "G1", {})
    asyncio.run(service.on_connect())
    assert service.state()["health"]["status"] == "CONNECTED_NO_TRADES"
    now = datetime.now(timezone.utc)
    frame = {
        "T": "q",
        "symbol": "SYNTHETICF",
        "time": (now - timedelta(seconds=40)).isoformat(),
        "bid": [{"price": 100, "qtty": 10}],
        "offer": [{"price": 101, "qtty": 10}],
    }
    asyncio.run(service.on_message(frame, now))
    state = service.state()
    assert state["health"]["status"] == "STALE"
    assert state["market"]["best_bid"] is None
    service.connected = False
    service.status = "DISCONNECTED"
    state = service.state()
    assert state["mode"] == "LIVE" and state["health"]["status"] == "DISCONNECTED"
    assert state["history"] == []


def test_invalid_crossed_book_and_unavailable_time_are_rejected():
    service = LiveService()
    service.contract = (datetime.now(timezone.utc).date(), "SYNTHETICF", "G1", {})
    now = datetime.now(timezone.utc)
    frame = {
        "T": "q",
        "symbol": "SYNTHETICF",
        "time": now.isoformat(),
        "bid": [{"price": 102, "qtty": 10}],
        "offer": [{"price": 101, "qtty": 10}],
    }
    asyncio.run(service.on_message(frame, now))
    frame["time"] = (now + timedelta(seconds=1)).isoformat()
    asyncio.run(service.on_message(frame, now))
    assert service.rejected == 2
    assert service.bid is None and service.accepted == 0


def test_reconnect_requires_new_trade_before_live():
    service = LiveService()
    service.contract = (datetime.now(timezone.utc).date(), "SYNTHETICF", "G1", {})
    asyncio.run(service.on_connect())
    now = datetime.now(timezone.utc)
    event = {"T": "te", "symbol": "SYNTHETICF", "time": now.isoformat(), "matchPrice": 100, "matchQtty": 7}
    asyncio.run(service.on_message(event, now))
    assert service.state()["health"]["status"] == "LIVE"
    service.connected = False
    service.status = "DISCONNECTED"
    assert service.state()["health"]["status"] == "DISCONNECTED"
    asyncio.run(service.on_connect())
    assert service.state()["health"]["status"] == "CONNECTED_NO_TRADES"


def test_instrument_pagination_uses_total_not_requested_page_size():
    from vn30.live import find_front

    expiry = (datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date() + timedelta(days=3)).isoformat()

    class Paged:
        def __init__(self):
            self.pages = []

        def get(self, operation, *, symbol=None, query=None):
            if operation == "instruments":
                self.pages.append(query["page"])
                if query["page"] == 1:
                    return {"data": [{"symbolType": "OTHER"}], "total": 2}
                return {
                    "data": [
                        {
                            "symbol": "SYNTHETICF",
                            "symbolType": "VN30F1M",
                            "marketId": "DVX",
                            "securityGroupId": "FU",
                        }
                    ],
                    "total": 2,
                }
            return [
                {
                    "symbol": symbol,
                    "productGrpId": "FIO",
                    "finalTradeDate": expiry,
                    "boardId": "G1",
                    "securityStatus": "NO_HALT",
                }
            ]

    client = Paged()
    assert find_front(client, datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date())[1] == "SYNTHETICF"
    assert client.pages == [1, 2]


def test_preflight_failure_never_reads_credentials_or_calls_rest(monkeypatch):
    from vn30.adapters.secure_dnse import TransportError

    async def denied():
        raise TransportError("network_blocked")

    def forbidden(*args, **kwargs):
        raise AssertionError("authenticated transport must not be created")

    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")
    monkeypatch.setattr("vn30.live.Credentials.from_environment", forbidden)
    service = LiveService(preflight_fn=denied, rest_factory=forbidden)
    asyncio.run(service.start())
    assert service.state()["health"]["status"] == "BLOCKED"
    assert service.state()["health"]["reason"] == "network_blocked"
    assert service.state()["history"] == []


def test_missing_credentials_after_preflight_remains_blocked(monkeypatch):
    monkeypatch.delenv("DNSE_API_KEY", raising=False)
    monkeypatch.delenv("DNSE_API_SECRET", raising=False)

    async def forbidden_preflight():
        raise AssertionError("không được thử mạng khi thiếu credentials")

    service = LiveService(preflight_fn=forbidden_preflight, rest_factory=FakeREST)
    asyncio.run(service.start())
    assert service.state()["health"]["status"] == "BLOCKED"
    assert service.state()["health"]["reason"] == "missing_credentials"
    assert service.state()["mode"] == "LIVE"


def test_rejects_invalid_depth_and_keeps_source_and_receive_clocks():
    service = LiveService()
    service.contract = (datetime.now(timezone.utc).date(), "SYNTHETICF", "G1", {})
    now = datetime.now(timezone.utc)
    frame = {
        "T": "q",
        "symbol": "SYNTHETICF",
        "time": (now - timedelta(seconds=1)).isoformat(),
        "bid": [{"price": 100, "qtty": 10}, {"price": 101, "qtty": 10}],
        "offer": [{"price": 102, "qtty": 10}],
    }
    asyncio.run(service.on_message(frame, now))
    assert service.rejected == 1 and not service.raw
    frame["bid"] = [{"price": 100, "qtty": 10}, {"price": 99, "qtty": 20}]
    asyncio.run(service.on_message(frame, now))
    assert service.accepted == 1
    raw, received, processed = service.raw[0]
    assert raw["time"] == frame["time"] and received == now and received <= processed
    assert service.state()["market"]["bid_depth_levels"] == 2


def test_ohlc_validation_requires_realistic_complete_nonfuture_bars():
    from vn30.live import valid_ohlc

    now = int(datetime.now(timezone.utc).timestamp())
    data = {"t": [now - 60], "o": [100], "h": [102], "l": [99], "c": [101], "v": [10]}
    assert valid_ohlc(data, now - 3600, now)
    assert not valid_ohlc({**data, "t": [now + 1]}, now - 3600, now)
    assert not valid_ohlc({**data, "c": []}, now - 3600, now)
    assert not valid_ohlc({**data, "c": [float("nan")]}, now - 3600, now)
    assert not valid_ohlc({"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}, now - 3600, now)


def test_rest_authentication_failure_remains_blocked_without_mock(monkeypatch):
    from vn30.adapters.secure_dnse import TransportError

    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")

    class DeniedREST:
        def __init__(self, credentials, *, authorized=False):
            pass

        def get(self, *args, **kwargs):
            raise TransportError("authentication_or_authorization_rejected")

    service = LiveService(preflight_fn=fake_preflight, rest_factory=DeniedREST)
    asyncio.run(service.start())
    data = service.state()
    assert data["mode"] == "LIVE" and data["health"]["status"] == "BLOCKED"
    assert data["health"]["reason"] == "authentication_or_authorization_rejected"
    assert data["history"] == [] and not service.raw
