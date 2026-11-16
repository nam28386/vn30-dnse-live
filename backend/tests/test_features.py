from datetime import timedelta

import pytest
from conftest import apply, at
from vn30.adapters import mock
from vn30.contracts import MARKET_RECORD, Quality
from vn30.features import FEATURES


def test_book_formulas(engine):
    q = mock.sequence(0)[1]
    q["bids"] = [{"price": 100, "quantity": 30}, {"price": 99, "quantity": 20}, {"price": 98, "quantity": 10}]
    q["asks"] = [
        {"price": 102, "quantity": 10},
        {"price": 103, "quantity": 10},
        {"price": 104, "quantity": 10},
    ]
    s, _ = apply(engine, q)
    v = s.values
    assert v["spread"].value == 2
    assert v["midprice"].value == 101
    assert v["depth"].value == 90
    assert v["imbalance"].value == pytest.approx(1 / 3)
    assert v["microprice"].value == 101.5
    assert set(v) == set(FEATURES)


def test_trade_vwap_signed_volume_cvd(engine):
    p = mock.sequence(0)[-1]
    s, _ = apply(engine, {**p, "price": 100, "quantity": 10, "side": "BUY"})
    s, _ = apply(engine, at({**p, "price": 104, "quantity": 30, "side": "SELL"}, 10))
    assert s.values["vwap"].value == 103
    assert s.values["signed_volume"].value == -30
    assert s.values["cvd"].value == -20
    assert s.values["cvd"].quality == Quality.INFERRED
    s, _ = apply(engine, at({**p, "side": "UNKNOWN", "side_provenance": "UNKNOWN"}, 20))
    assert s.values["signed_volume"].value is None
    assert s.values["cvd"].value == -20
    assert s.values["cvd"].quality == Quality.INVALID


def test_ma21_completed_minutes_only(engine):
    trade = mock.sequence(0)[-1]
    for i in range(21):
        s, _ = apply(engine, at({**trade, "price": 100 + i}, i * 60))
    assert s.values["ma21"].quality == Quality.WARMUP
    s, _ = apply(engine, at({**trade, "price": 9999}, 21 * 60))
    assert s.values["ma21"].value == 110  # excludes unfinished 9999 bar


def test_basis_official_only_and_staleness(engine):
    index = mock.sequence(0)[0]
    apply(engine, {**index, "value": 100})
    s, _ = apply(engine, {**mock.sequence(0)[-1], "price": 102})
    assert s.values["basis"].value == 2
    s, _ = apply(engine, at({**index, "value": 1, "estimated": True}, 10))
    assert s.values["basis"].value == 2
    s, _ = apply(engine, at(mock.sequence(0)[-1], 20))
    assert s.values["basis"].value is None
    assert s.values["basis"].quality == Quality.STALE


def test_missing_zero_depth_and_stale_quotes(engine):
    s, _ = apply(engine, mock.sequence(0)[-1])
    assert s.values["spread"].quality == Quality.MISSING
    q = mock.sequence(0)[1]
    s, _ = apply(
        engine, {**at(q, 1), "bids": [{"price": 100, "quantity": 0}], "asks": [{"price": 102, "quantity": 0}]}
    )
    assert s.values["imbalance"].value is None
    assert s.values["microprice"].quality == Quality.MISSING
    s, _ = apply(engine, at(mock.sequence(0)[-1], 30))
    assert s.values["spread"].quality == Quality.STALE
    assert s.values["spread"].value is None


def test_session_boundary_resets(engine):
    apply(engine, mock.sequence(0)[-1])
    s, _ = apply(engine, at(mock.session(0, "BREAK", "next"), 20))
    assert s.values["vwap"].value is None
    assert s.values["cvd"].value is None
    assert s.values["ma21"].quality == Quality.WARMUP
    with pytest.raises(ValueError, match="session"):
        apply(engine, at(mock.sequence(0)[-1], 30))


def test_temporal_cutoff_and_out_of_order(engine):
    r = MARKET_RECORD.validate_python(mock.sequence(0)[-1])
    with pytest.raises(ValueError, match="not yet available"):
        engine.apply(r, r.available_at - timedelta(microseconds=1))
    engine.apply(r, r.available_at)
    old = MARKET_RECORD.validate_python(at(mock.sequence(0)[-1], -5))
    with pytest.raises(ValueError, match="out-of-order"):
        engine.apply(old, r.available_at)
    with pytest.raises(ValueError, match="regress"):
        engine.apply(old, old.available_at)


def test_delayed_source_is_stale_even_when_newly_received(engine):
    q = mock.sequence(0)[1]
    r = MARKET_RECORD.validate_python({**at(q, 30), "event_time": mock.BASE})
    s = engine.apply(r, r.available_at)
    assert s.values["quote_age"].value == 30
    assert s.values["spread"].quality == Quality.STALE


def test_future_changes_cannot_rewrite_past_snapshot(engine):
    s, _ = apply(engine, mock.sequence(0)[-1])
    frozen = s.model_dump_json()
    for i in range(1, 20):
        apply(engine, mock.sequence(i)[-1])
    assert s.model_dump_json() == frozen
    assert all(x.available_at <= s.decision_time for x in s.values.values())
