import asyncio
import logging
from collections import deque
from pathlib import Path

from .adapters import mock
from .adapters.dnse import discover_front_contract
from .contracts import EventStatus, FeedQualityState, Quality
from .events import TERMINAL, EventManager
from .features import FEATURES, FeatureEngine
from .storage import Journal

logger = logging.getLogger(__name__)


class ResearchService:
    def __init__(self, data_dir: Path):
        self.journal = Journal(data_dir)
        self.instruments = [self.journal.ingest(x) for x in mock.metadata()]
        self.instrument = discover_front_contract(self.instruments, mock.BASE)
        self.engine = FeatureEngine(self.instrument.symbol)
        self.manager = EventManager()
        self.history = deque(maxlen=600)
        self.snapshot = None
        self.step = 0
        self.rejected = self.reconnects = 0
        self.connected = True
        self.ingest(mock.session(-1))

    def ingest(self, payload):
        try:
            record = self.journal.ingest(payload)
            snapshot = self.engine.apply(record, record.available_at)
        except ValueError:
            self.rejected += 1
            self.journal.reject(
                payload.get("event_id", "UNKNOWN"), "schema, duplicate, session, or temporal rejection"
            )
            logger.warning("market record rejected", extra={"metadata": {"kind": payload.get("kind")}})
            return
        self.snapshot = snapshot
        previous = {x.event_id: x.model_dump_json() for x in self.manager.events}
        self.manager.observe(snapshot, record)
        self.journal.derived(snapshot)
        for event in self.manager.events:
            if previous.get(event.event_id) != event.model_dump_json():
                self.journal.derived(event)
        if record.kind == "trade":
            self.history.append(
                {
                    "time": record.event_time.isoformat(),
                    "price": record.price,
                    "quantity": record.quantity,
                    "side": record.side,
                    "available_at": snapshot.available_at.isoformat(),
                    **{name: value.value for name, value in snapshot.values.items()},
                }
            )

    def tick(self):
        for payload in mock.sequence(self.step, self.instrument.symbol):
            self.ingest(payload)
        self.step += 1

    def bootstrap(self, steps=150):
        for _ in range(steps):
            self.tick()

    def feed_quality(self):
        s = self.snapshot
        qa, ia = s.values["quote_age"].value, s.values["index_age"].value
        quality = (
            Quality.STALE
            if not self.connected
            else Quality.MISSING
            if qa is None or ia is None
            else Quality.STALE
            if qa > 15 or ia > 15
            else Quality.MISSING
            if s.values["spread"].value is None
            else Quality.GOOD
        )
        return FeedQualityState(
            event_id=f"health:{s.event_id}",
            source="MOCK",
            event_time=s.event_time,
            received_at=s.received_at,
            processed_at=s.processed_at,
            available_at=s.available_at,
            raw_ref=s.raw_ref,
            connected=self.connected,
            quote_age_seconds=qa,
            index_age_seconds=ia,
            rejected_records=self.rejected,
            reconnects=self.reconnects,
            quality=quality,
            message="Deterministic accelerated replay • simulated clock • MBP • inferred side",
        )

    def state(self):
        return dict(
            mode="MOCK",
            version="0.1.0",
            clock="SIMULATED",
            replay_speed="10 market seconds / tick",
            instrument=self.instrument.model_dump(mode="json"),
            snapshot=self.snapshot.model_dump(mode="json"),
            history=list(self.history),
            events=[x.model_dump(mode="json") for x in self.manager.events[-30:]],
            health=self.feed_quality().model_dump(mode="json"),
        )

    def transport_gap(self):
        """Conservative gap boundary. No recovery/markout may bridge a transport outage."""
        self.connected = False
        for i, event in enumerate(self.manager.events):
            if event.status not in TERMINAL:
                self.manager.events[i] = self.manager.transition(
                    event, EventStatus.CENSORED, self.snapshot.decision_time, "transport disconnected"
                )
                self.journal.derived(self.manager.events[i])
        self.engine.quote = self.engine.index = None
        self.engine.contaminated = True

    async def run(self, interval):
        while True:
            await asyncio.sleep(interval)
            try:
                if not self.connected:
                    self.reconnects += 1
                    self.connected = True
                self.tick()
            except (ConnectionError, TimeoutError):
                self.transport_gap()
                logger.warning("feed reconnect scheduled", extra={"metadata": {"attempt": self.reconnects}})


def feature_contracts():
    return {
        k: dict(
            formula=v[0],
            unit=v[1],
            sources=v[2],
            version="1.0.0",
            availability="at processing decision time; only inputs available by that time",
        )
        for k, v in FEATURES.items()
    }
