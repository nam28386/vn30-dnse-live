"""Deterministic, arrival-ordered features; no retrospective corrections."""

from collections import deque
from datetime import datetime

from .contracts import (
    FeatureSnapshot,
    FeatureValue,
    MarketIndex,
    MarketRecord,
    MarketTrade,
    Quality,
    QuoteSnapshot,
    SessionState,
)

# Public machine-readable research contract; formulas documented in docs/FEATURES.md.
FEATURES = {
    "spread": ("ask1 - bid1", "index points", ["quote"]),
    "midprice": ("(ask1 + bid1) / 2", "index points", ["quote"]),
    "depth": ("sum(bid_qty[1:k]) + sum(ask_qty[1:k])", "contracts", ["quote"]),
    "imbalance": ("(bid_depth - ask_depth) / total_depth", "ratio", ["quote"]),
    "microprice": ("(ask1 * bid_qty1 + bid1 * ask_qty1) / (bid_qty1 + ask_qty1)", "index points", ["quote"]),
    "signed_volume": ("inferred sign * last trade quantity; unknown -> null", "contracts", ["trade"]),
    "cvd": ("session sum of known inferred signed quantities", "contracts", ["trade", "session"]),
    "vwap": ("session sum(price * qty) / sum(qty)", "index points", ["trade", "session"]),
    "ma21": ("mean of last 21 completed one-minute trade-bar closes", "index points", ["trade", "session"]),
    "basis": ("latest trade price - official VN30 index", "index points", ["trade", "index"]),
    "quote_age": ("max(source event age, local availability age)", "seconds", ["quote"]),
    "index_age": ("max(source event age, local availability age)", "seconds", ["index"]),
}


class FeatureEngine:
    def __init__(self, symbol: str, k: int = 3, max_age: float = 15):
        if k < 1 or max_age <= 0:
            raise ValueError("positive k and freshness limit required")
        self.symbol, self.k, self.max_age = symbol, k, max_age
        self.quote: QuoteSnapshot | None = None
        self.index: MarketIndex | None = None
        self.trade: MarketTrade | None = None
        self.session: SessionState | None = None
        self.cvd, self.notional, self.volume = 0.0, 0.0, 0
        self.unknown_volume = 0
        self.minute: datetime | None = None
        self.close: float | None = None
        self.closes: deque[float] = deque(maxlen=21)
        self.dependencies: list[str] = []
        self.previous_snapshot_id: str | None = None
        self.contaminated = False
        self.last_decision: datetime | None = None
        self.latest_source: dict[str, datetime] = {}

    @staticmethod
    def age(record, now):
        if record is None:
            return None
        return max(
            0.0, (now - record.event_time).total_seconds(), (now - record.available_at).total_seconds()
        )

    def apply(self, record: MarketRecord, now: datetime) -> FeatureSnapshot:
        if record.available_at > now or record.event_time > now:
            raise ValueError("record not yet available at decision time")
        if self.last_decision and now < self.last_decision:
            raise ValueError("decision clock cannot regress")
        symbol = getattr(record, "symbol", self.symbol)
        if symbol != self.symbol:
            raise ValueError("instrument mismatch")
        # Historical/out-of-order source messages remain in journal but cannot rewrite current state.
        source_key = (
            "estimated_index" if isinstance(record, MarketIndex) and record.estimated else record.kind
        )
        if source_key in self.latest_source and record.event_time < self.latest_source[source_key]:
            raise ValueError("out-of-order source event")
        if isinstance(record, (MarketTrade, QuoteSnapshot)) and (
            self.session is None
            or record.session_id != self.session.session_id
            or self.session.phase != "CONTINUOUS"
        ):
            raise ValueError("trade/quote outside matching continuous session")
        self.last_decision = now
        self.latest_source[source_key] = record.event_time
        if isinstance(record, SessionState):
            if (
                self.session is None
                or record.session_id != self.session.session_id
                or record.phase != self.session.phase
            ):
                self.quote = self.trade = None
                self.index = None
                self.cvd = self.notional = 0.0
                self.volume = self.unknown_volume = 0
                self.minute = self.close = None
                self.closes.clear()
                self.dependencies.clear()
                self.previous_snapshot_id = None
                self.contaminated = False
            self.session = record
        self.dependencies = ([self.previous_snapshot_id] if self.previous_snapshot_id else []) + [
            record.event_id
        ]
        if isinstance(record, QuoteSnapshot):
            self.quote = record
        elif isinstance(record, MarketIndex) and not record.estimated:
            self.index = record
        elif isinstance(record, MarketTrade):
            minute = record.event_time.replace(second=0, microsecond=0)
            if self.minute is not None and minute > self.minute:
                self.closes.append(self.close)
            self.minute, self.close = minute, record.price
            self.trade = record
            self.volume += record.quantity
            self.notional += record.quantity * record.price
            if record.side == "UNKNOWN":
                self.unknown_volume += record.quantity
            else:
                self.cvd += record.quantity * (1 if record.side == "BUY" else -1)
        result = self.snapshot(now, record)
        self.previous_snapshot_id = result.event_id
        return result

    def snapshot(self, now: datetime, trigger) -> FeatureSnapshot:
        values: dict[str, FeatureValue] = {}

        def put(name, value, quality=Quality.GOOD, deps=()):
            values[name] = FeatureValue(value=value, quality=quality, available_at=now, dependencies=deps)

        qa, ia = self.age(self.quote, now), self.age(self.index, now)
        put(
            "quote_age",
            qa,
            Quality.MISSING if qa is None else Quality.STALE if qa > self.max_age else Quality.GOOD,
        )
        put(
            "index_age",
            ia,
            Quality.MISSING if ia is None else Quality.STALE if ia > self.max_age else Quality.GOOD,
        )
        q = self.quote
        for name in ("spread", "midprice", "depth", "imbalance", "microprice"):
            put(name, None, Quality.MISSING)
        if q and q.bids and q.asks:
            b, a = q.bids[0], q.asks[0]
            bd, ad = sum(x.quantity for x in q.bids[: self.k]), sum(x.quantity for x in q.asks[: self.k])
            quality = Quality.STALE if qa > self.max_age else Quality.GOOD
            book = {
                "spread": a.price - b.price,
                "midprice": (a.price + b.price) / 2,
                "depth": bd + ad,
                "imbalance": (bd - ad) / (bd + ad) if bd + ad else None,
                "microprice": (a.price * b.quantity + b.price * a.quantity) / (b.quantity + a.quantity)
                if b.quantity + a.quantity
                else None,
            }
            for name, value in book.items():
                put(
                    name,
                    value if quality == Quality.GOOD else None,
                    Quality.MISSING if value is None else quality,
                    (q.event_id,),
                )
        t = self.trade
        sign = (1 if t.side == "BUY" else -1) if t and t.side != "UNKNOWN" else None
        put(
            "signed_volume",
            sign * t.quantity if sign else None,
            Quality.INFERRED if sign else Quality.MISSING,
            (t.event_id,) if t else (),
        )
        put(
            "cvd",
            self.cvd if self.volume else None,
            Quality.MISSING
            if not self.volume
            else Quality.INVALID
            if self.unknown_volume or self.contaminated
            else Quality.INFERRED,
            tuple(self.dependencies),
        )
        put(
            "vwap",
            self.notional / self.volume if self.volume else None,
            Quality.INVALID if self.contaminated else Quality.GOOD if self.volume else Quality.MISSING,
            tuple(self.dependencies),
        )
        put(
            "ma21",
            sum(self.closes) / 21 if len(self.closes) == 21 else None,
            Quality.INVALID
            if self.contaminated
            else Quality.GOOD
            if len(self.closes) == 21
            else Quality.WARMUP,
            tuple(self.dependencies),
        )
        fresh_trade = t and self.age(t, now) <= self.max_age
        valid_basis = fresh_trade and self.index and ia <= self.max_age
        put(
            "basis",
            t.price - self.index.value if valid_basis else None,
            Quality.GOOD if valid_basis else Quality.MISSING if not t or not self.index else Quality.STALE,
            tuple(x.event_id for x in (t, self.index) if x),
        )
        return FeatureSnapshot(
            event_id=f"features:{trigger.event_id}",
            source=trigger.source,
            event_time=trigger.event_time,
            received_at=trigger.received_at,
            processed_at=now,
            available_at=now,
            raw_ref=trigger.raw_ref,
            symbol=self.symbol,
            session_id=self.session.session_id if self.session else None,
            decision_time=now,
            values=values,
        )
