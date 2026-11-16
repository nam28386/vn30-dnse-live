from datetime import timedelta

from conftest import apply, at
from vn30.adapters import mock
from vn30.contracts import EventStatus as S
from vn30.events import EventManager


def observe(engine, manager, payload):
    s, r = apply(engine, payload)
    manager.observe(s, r)
    return s


def setup_shock(engine):
    m = EventManager(horizon_seconds=30)
    observe(engine, m, at(mock.sequence(0)[1], 0))
    observe(engine, m, at({**mock.sequence(0)[-1], "quantity": 100, "side": "BUY"}, 1))
    return m


def test_lifecycle_no_premature_markouts_and_recovery(engine):
    m = setup_shock(engine)
    assert m.events[0].status == S.DETECTED
    q = mock.sequence(0)[1]
    for seconds in (2, 5, 15, 30):
        observe(engine, m, at(q, seconds))
        assert m.events[0].markout is None
    observe(engine, m, at(q, 32))
    e = m.events[0]
    assert e.status == S.OBSERVING_RECOVERY
    assert e.markout_observed_at >= e.horizon_at
    assert e.markout_source_time >= e.horizon_at
    observe(engine, m, at(q, 33))
    e = m.events[0]
    assert e.status == S.MATURED
    assert e.spread_recovery_seconds == 1
    assert e.depth_recovery_seconds == 1
    assert [t.status for t in e.transitions] == [
        S.DETECTED,
        S.ACTIVE,
        S.MARKOUT_PENDING,
        S.OBSERVING_RECOVERY,
        S.MATURED,
    ]


def test_cannot_use_carried_pre_horizon_quote(engine):
    m = setup_shock(engine)
    q = mock.sequence(0)[1]
    for seconds in (2, 5, 15, 29):
        observe(engine, m, at(q, seconds))
    observe(engine, m, at(mock.sequence(0)[0], 32))
    assert m.events[0].markout is None
    delayed_quote = {**at(q, 33), "event_time": mock.BASE + timedelta(seconds=30)}
    observe(engine, m, delayed_quote)
    assert m.events[0].markout is None


def test_spread_depth_recovery_and_impact_retention(engine):
    m = setup_shock(engine)
    q = mock.sequence(0)[1]
    mid = m.events[0].baseline_mid

    def moved(seconds, shift, spread, qty):
        return at(
            {
                **q,
                "bids": [{"price": mid + shift - spread / 2, "quantity": qty}],
                "asks": [{"price": mid + shift + spread / 2, "quantity": qty}],
            },
            seconds,
        )

    observe(engine, m, moved(2, 2, 2, 10))
    observe(engine, m, moved(5, 2, 2, 10))
    observe(engine, m, moved(15, 2, 2, 10))
    observe(engine, m, moved(25, 2, 2, 10))
    observe(engine, m, moved(32, 1, 0.1, 1000))
    assert m.events[0].markout == 1
    assert m.events[0].impact_retention == 0.5
    assert m.events[0].spread_recovery_seconds == 31
    assert m.events[0].depth_recovery_seconds == 31


def test_missing_quote_and_session_transition_censor(engine):
    m = setup_shock(engine)
    observe(engine, m, at(mock.sequence(0)[0], 20))
    assert m.events[0].status == S.CENSORED
    assert m.events[0].markout is None


def test_session_censors(engine):
    m = setup_shock(engine)
    observe(engine, m, at(mock.session(0, "BREAK"), 5))
    assert m.events[0].status == S.CENSORED


def test_unknown_side_or_missing_baseline_invalid(engine):
    m = EventManager()
    observe(
        engine, m, {**mock.sequence(0)[-1], "quantity": 100, "side": "UNKNOWN", "side_provenance": "UNKNOWN"}
    )
    assert m.events[0].status == S.INVALID
    assert m.events[0].markout is None


def test_measurement_revision_not_backdated(engine):
    from vn30.contracts import ShockEvent

    m = setup_shock(engine)
    q = mock.sequence(0)[1]
    mid = m.events[0].baseline_mid
    wide = {**q, "bids": [{"price": mid - 1, "quantity": 1}], "asks": [{"price": mid + 1, "quantity": 1}]}
    observe(engine, m, at(wide, 2))
    observe(engine, m, at(wide, 5))
    observe(engine, m, at(q, 10))
    e = m.events[0]
    assert e.status == S.MARKOUT_PENDING
    assert e.available_at == mock.BASE + timedelta(seconds=10)
    assert e.spread_recovery_seconds == 9
    assert "quote:10" in e.observation_refs
    assert ShockEvent.model_validate_json(e.model_dump_json()) == e


def test_invalid_unknown_direction_is_not_sell(engine):
    m = EventManager()
    observe(
        engine, m, {**mock.sequence(0)[-1], "quantity": 100, "side": "UNKNOWN", "side_provenance": "UNKNOWN"}
    )
    e = m.events[0]
    assert e.direction is None
    assert e.baseline_mid is None
