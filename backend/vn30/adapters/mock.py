"""Deterministic research fixture, synthetic identifiers, no network or credentials."""

import math
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 1, 5, 2, 0, tzinfo=timezone.utc)


def envelope(kind, step, offset=0):
    t = BASE + timedelta(seconds=step * 10, milliseconds=offset)
    eid = f"mock:{step}:{kind}"
    return dict(
        kind=kind,
        event_id=eid,
        source="MOCK",
        event_time=t.isoformat(),
        received_at=(t + timedelta(milliseconds=25)).isoformat(),
        processed_at=(t + timedelta(milliseconds=30)).isoformat(),
        available_at=(t + timedelta(milliseconds=30)).isoformat(),
        raw_ref=eid,
    )


def metadata():
    return [
        dict(
            **envelope("instrument", -1),
            symbol="MOCK-VN30-NEAR",
            underlying="VN30",
            instrument_type="FUTURE",
            expiry="2026-01-15",
            listed_on="2025-12-01",
            tick_size=0.1,
            board_id="MOCK",
        ),
        dict(
            **{
                **envelope("instrument", -1),
                "event_id": "mock:next:instrument",
                "raw_ref": "mock:next:instrument",
            },
            symbol="MOCK-VN30-NEXT",
            underlying="VN30",
            instrument_type="FUTURE",
            expiry="2026-02-19",
            listed_on="2025-12-01",
            tick_size=0.1,
            board_id="MOCK",
        ),
    ]


def session(step, phase="CONTINUOUS", session_id="2026-01-05:AM"):
    return dict(**envelope("session", step), session_id=session_id, phase=phase, trading_date="2026-01-05")


def sequence(step, symbol="MOCK-VN30-NEAR"):
    """Each 80-step block includes a flow burst, depleted/wide book, and recovery.

    Steps 56..59 omit quotes to demonstrate stale inputs and censoring.
    """
    phase = step % 80
    wave = 1.6 * math.sin(step / 18) + 0.5 * math.sin(step / 3)
    bump = 1.2 if 30 <= phase < 34 else 0
    mid = round(1850 + wave + bump, 1)
    spread = 0.6 if 30 <= phase < 33 else 0.2
    scale = 0.3 if 30 <= phase < 34 else 1
    bids = [
        dict(
            price=round(mid - spread / 2 - i * 0.1, 1),
            quantity=int(scale * (100 + i * 35 + 20 * math.sin(step))),
        )
        for i in range(3)
    ]
    asks = [
        dict(
            price=round(mid + spread / 2 + i * 0.1, 1),
            quantity=int(scale * (110 + i * 25 + 20 * math.cos(step))),
        )
        for i in range(3)
    ]
    common = dict(symbol=symbol, session_id="2026-01-05:AM")
    result = [dict(**envelope("index", step), value=round(1847 + wave * 0.7, 2))]
    if phase not in (56, 57, 58, 59):
        result.append(dict(**envelope("quote", step, 1), **common, bids=bids, asks=asks))
    result.append(
        dict(
            **envelope("trade", step, 2),
            **common,
            price=round(mid + (0.1 if step % 3 else -0.1), 1),
            quantity=100 if phase == 30 else 5 + step % 19,
            side="BUY" if step % 3 else "SELL",
            side_provenance="MOCK_INFERRED",
        )
    )
    return result
