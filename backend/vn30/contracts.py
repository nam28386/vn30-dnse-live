from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class Quality(StrEnum):
    GOOD = "GOOD"
    INFERRED = "INFERRED"
    STALE = "STALE"
    MISSING = "MISSING"
    WARMUP = "WARMUP"
    INVALID = "INVALID"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: str
    source: Literal["MOCK", "DNSE"] = "MOCK"
    event_time: AwareDatetime
    received_at: AwareDatetime
    processed_at: AwareDatetime
    available_at: AwareDatetime
    raw_ref: str

    @model_validator(mode="after")
    def clocks(self):
        if not self.received_at <= self.processed_at <= self.available_at:
            raise ValueError("require received_at <= processed_at <= available_at")
        return self


class MarketTrade(Record):
    kind: Literal["trade"] = "trade"
    symbol: str
    session_id: str
    price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    side: Literal["BUY", "SELL", "UNKNOWN"] = "UNKNOWN"
    side_provenance: Literal["MOCK_INFERRED", "VENDOR_INFERRED", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def side_evidence(self):
        if self.side != "UNKNOWN" and self.side_provenance == "UNKNOWN":
            raise ValueError("signed side requires explicit inference provenance")
        return self


class Level(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    price: float = Field(gt=0)
    quantity: int = Field(ge=0)


class QuoteSnapshot(Record):
    kind: Literal["quote"] = "quote"
    symbol: str
    session_id: str
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    book_type: Literal["MBP"] = "MBP"

    @model_validator(mode="after")
    def ordered(self):
        if any(a.price <= b.price for a, b in zip(self.bids, self.bids[1:])):
            raise ValueError("bids must be strictly descending")
        if any(a.price >= b.price for a, b in zip(self.asks, self.asks[1:])):
            raise ValueError("asks must be strictly ascending")
        if self.bids and self.asks and self.bids[0].price > self.asks[0].price:
            raise ValueError("crossed book")
        return self


class MarketIndex(Record):
    kind: Literal["index"] = "index"
    name: Literal["VN30"] = "VN30"
    value: float = Field(gt=0)
    estimated: bool = False


class InstrumentMetadata(Record):
    kind: Literal["instrument"] = "instrument"
    symbol: str
    underlying: str
    instrument_type: Literal["FUTURE", "INDEX"]
    expiry: date | None = None
    listed_on: date
    tick_size: float = Field(gt=0)
    board_id: str
    tradable: bool = True


class SessionState(Record):
    kind: Literal["session"] = "session"
    session_id: str
    phase: Literal["CONTINUOUS", "AUCTION", "BREAK", "CLOSED"]
    trading_date: date


MarketRecord = Annotated[
    MarketTrade | QuoteSnapshot | MarketIndex | InstrumentMetadata | SessionState,
    Field(discriminator="kind"),
]
MARKET_RECORD = TypeAdapter(MarketRecord)


class FeatureValue(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    value: float | None
    quality: Quality
    available_at: AwareDatetime
    dependencies: tuple[str, ...] = ()
    version: Literal["1.0.0"] = "1.0.0"


class FeatureSnapshot(Record):
    kind: Literal["features"] = "features"
    symbol: str
    session_id: str | None
    decision_time: AwareDatetime
    values: dict[str, FeatureValue]

    @model_validator(mode="after")
    def information_set(self):
        if self.available_at > self.decision_time:
            raise ValueError("snapshot unavailable at decision time")
        if any(v.available_at > self.decision_time for v in self.values.values()):
            raise ValueError("future dependency")
        return self


class EventStatus(StrEnum):
    DETECTED = "DETECTED"
    ACTIVE = "ACTIVE"
    MARKOUT_PENDING = "MARKOUT_PENDING"
    OBSERVING_RECOVERY = "OBSERVING_RECOVERY"
    MATURED = "MATURED"
    INVALID = "INVALID"
    CENSORED = "CENSORED"


class Transition(BaseModel):
    status: EventStatus
    at: AwareDatetime
    reason: str


class ShockEvent(Record):
    kind: Literal["shock"] = "shock"
    symbol: str
    session_id: str
    status: EventStatus = EventStatus.DETECTED
    direction: Literal[-1, 1] | None
    quantity: int
    baseline_mid: float | None
    baseline_spread: float | None
    baseline_depth: float | None
    observation_refs: tuple[str, ...] = ()
    horizon_at: AwareDatetime
    markout: float | None = None
    markout_observed_at: AwareDatetime | None = None
    markout_source_time: AwareDatetime | None = None
    initial_impact: float | None = None
    impact_retention: float | None = None
    spread_recovery_seconds: float | None = None
    depth_recovery_seconds: float | None = None
    transitions: tuple[Transition, ...] = ()

    @model_validator(mode="after")
    def mature_clock(self):
        if self.status not in (EventStatus.INVALID, EventStatus.CENSORED) and any(
            x is None for x in (self.direction, self.baseline_mid, self.baseline_spread, self.baseline_depth)
        ):
            raise ValueError("active event requires baseline and inferred direction")
        if self.markout_observed_at is not None and self.available_at < self.markout_observed_at:
            raise ValueError("event revision cannot predate markout availability")
        if self.markout is not None and (
            self.markout_observed_at is None
            or self.markout_observed_at < self.horizon_at
            or self.markout_source_time is None
            or self.markout_source_time < self.horizon_at
        ):
            raise ValueError("markout requires a post-horizon observation")
        return self


class FeedQualityState(Record):
    kind: Literal["feed_quality"] = "feed_quality"
    connected: bool
    mode: Literal["MOCK", "LIVE"] = "MOCK"
    quote_age_seconds: float | None
    index_age_seconds: float | None
    rejected_records: int
    reconnects: int
    quality: Quality
    message: str


def iso(t: datetime) -> str:
    return t.isoformat()
