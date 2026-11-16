from datetime import timedelta

import pytest
from pydantic import ValidationError
from vn30.adapters import mock
from vn30.adapters.dnse import discover_front_contract
from vn30.contracts import MARKET_RECORD, InstrumentMetadata


def test_schemas_roundtrip():
    for payload in [*mock.metadata(), mock.session(-1), *mock.sequence(0)]:
        r = MARKET_RECORD.validate_python(payload)
        assert MARKET_RECORD.validate_json(r.model_dump_json()) == r
        assert r.schema_version == "1.0.0"


@pytest.mark.parametrize(
    "mutation",
    [
        {"received_at": "2026-01-05T09:00:00"},
        {"processed_at": "2025-01-01T00:00:00Z"},
        {"quantity": -1},
        {"price": float("nan")},
        {"side_provenance": "UNKNOWN"},
        {"extra": "unexpected"},
    ],
)
def test_reject_malformed_trade(mutation):
    with pytest.raises(ValidationError):
        MARKET_RECORD.validate_python({**mock.sequence(0)[-1], **mutation})


def test_mbp_only_and_ordered():
    q = mock.sequence(0)[1]
    for change in (
        {"book_type": "MBO"},
        {"bids": list(reversed(q["bids"]))},
        {"asks": [{"price": 1, "quantity": 1}]},
    ):
        with pytest.raises(ValidationError):
            MARKET_RECORD.validate_python({**q, **change})


def test_contract_discovery_uses_only_known_unexpired_metadata():
    instruments = [InstrumentMetadata.model_validate(x) for x in mock.metadata()]
    assert discover_front_contract(instruments, mock.BASE).symbol == "MOCK-VN30-NEAR"
    assert discover_front_contract(instruments, mock.BASE + timedelta(days=12)).symbol == "MOCK-VN30-NEXT"
    with pytest.raises(LookupError):
        discover_front_contract(instruments, mock.BASE + timedelta(days=100))
    with pytest.raises(LookupError):
        discover_front_contract(
            [x.model_copy(update={"available_at": mock.BASE + timedelta(days=1)}) for x in instruments],
            mock.BASE,
        )
