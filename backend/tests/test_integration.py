import hashlib
import json

import polars as pl
from fastapi.testclient import TestClient
from vn30.adapters import mock
from vn30.api import create_app
from vn30.contracts import EventStatus, Quality
from vn30.logging import redact
from vn30.service import ResearchService


def test_raw_normalized_and_parquet(tmp_path):
    s = ResearchService(tmp_path)
    s.bootstrap(40)
    raw = [json.loads(x) for x in (s.journal.root / "raw/events.jsonl").read_text().splitlines()]
    for row in raw:
        encoded = json.dumps(row["payload"], separators=(",", ":"), sort_keys=True)
        assert hashlib.sha256(encoded.encode()).hexdigest() == row["sha256"]
    normalized = s.journal.db.execute("SELECT payload FROM records WHERE kind='trade' LIMIT 1").fetchone()[0]
    assert json.loads(normalized)["raw_ref"].startswith("sha256:")
    s.journal.export()
    frame = pl.read_parquet(s.journal.root / "normalized/records.parquet")
    assert frame.height == len(raw)
    assert "payload" in frame.columns
    assert pl.read_parquet(s.journal.root / "normalized/derived.parquet").height > 0
    s.journal.close()


def test_replay_is_deterministic_and_rejects_duplicates(tmp_path):
    a, b = ResearchService(tmp_path / "a"), ResearchService(tmp_path / "b")
    a.bootstrap(65)
    b.bootstrap(65)
    assert a.state() == b.state()
    before = a.engine.volume
    a.ingest(mock.sequence(64)[-1])
    assert a.rejected == 1
    assert a.engine.volume == before
    a.journal.close()
    b.journal.close()


def test_read_only_api_and_websocket(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, bootstrap_steps=35, stream=False)) as client:
        state = client.get("/api/state").json()
        assert state["mode"] == "MOCK"
        assert len(state["history"]) == 35
        assert state["snapshot"]["values"]["vwap"]["value"] > 0
        assert len(client.get("/api/events").json()) == 1
        assert client.get("/api/instruments").status_code == 200
        assert client.get("/api/features/definitions").json()["basis"]["unit"] == "index points"
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, "/api/state").status_code == 405
            assert client.request(method, "/api/orders").status_code == 404
        with client.websocket_connect("/api/stream") as ws:
            assert ws.receive_json()["history"] == state["history"]


def test_live_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("VN30_MODE", "LIVE")
    with TestClient(create_app(data_dir=tmp_path, stream=False)) as client:
        state = client.get("/api/state").json()
        assert state["mode"] == "LIVE"
        assert state["health"]["status"] == "BLOCKED"
        assert state["history"] == []
        assert state["market"]["best_bid"] is None
    assert not list(tmp_path.iterdir())


def test_transport_gap_censors_and_degrades_aggregates(tmp_path):
    s = ResearchService(tmp_path)
    s.bootstrap(31)
    s.transport_gap()
    assert not s.connected
    assert s.manager.events[-1].status == EventStatus.CENSORED
    s.tick()
    assert s.snapshot.values["cvd"].quality == Quality.INVALID
    assert s.snapshot.values["vwap"].quality == Quality.INVALID
    assert s.snapshot.values["ma21"].quality == Quality.INVALID
    s.journal.close()


def test_secret_redaction():
    secret = {
        "api_key": "hidden",
        "nested": {"Authorization": "Bearer hidden"},
        "rows": [{"signature": "hidden"}],
        "message": "token=hidden status=ok",
        "auth_message": "Authorization: Bearer hidden",
    }
    assert "hidden" not in json.dumps(redact(secret))


def test_healthz_is_nonsensitive_in_mock_and_blocked_live(tmp_path, monkeypatch):
    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET")
    monkeypatch.setenv("VN30_MODE", "MOCK")
    with TestClient(create_app(data_dir=tmp_path / "mock", bootstrap_steps=2, stream=False)) as client:
        assert client.get("/healthz").json() == {"status": "ok", "mode": "MOCK"}
    monkeypatch.setenv("VN30_MODE", "LIVE")
    with TestClient(create_app(data_dir=tmp_path / "live", stream=False)) as client:
        result = client.get("/healthz").json()
        assert result == {"status": "ok", "mode": "LIVE"}
        assert "SYNTHETIC" not in str(result)
        assert client.get("/api/health").json()["status"] == "BLOCKED"
