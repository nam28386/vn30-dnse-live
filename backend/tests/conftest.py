from datetime import timedelta

import pytest
from vn30.adapters import mock
from vn30.contracts import MARKET_RECORD
from vn30.features import FeatureEngine


@pytest.fixture
def engine():
    e = FeatureEngine("MOCK-VN30-NEAR")
    s = MARKET_RECORD.validate_python(mock.session(-1))
    e.apply(s, s.available_at)
    return e


def apply(engine, payload):
    record = MARKET_RECORD.validate_python(payload)
    return engine.apply(record, record.available_at), record


def at(payload, seconds):
    t = mock.BASE + timedelta(seconds=seconds)
    return {
        **payload,
        "event_time": t,
        "received_at": t,
        "processed_at": t,
        "available_at": t,
        "event_id": f"{payload['kind']}:{seconds}",
        "raw_ref": f"fixture:{seconds}",
    }
