from datetime import timedelta

from .contracts import EventStatus as S
from .contracts import FeatureSnapshot, MarketTrade, Quality, ShockEvent, Transition

TERMINAL = {S.MATURED, S.INVALID, S.CENSORED}


class EventManager:
    """Fixture-calibrated descriptive flow events, not trade recommendations."""

    def __init__(self, threshold=80, horizon_seconds=30, recovery_timeout=120):
        self.threshold, self.horizon, self.timeout = threshold, horizon_seconds, recovery_timeout
        self.events: list[ShockEvent] = []

    def transition(self, event, status, now, reason):
        return event.model_copy(
            update={
                "status": status,
                "processed_at": now,
                "available_at": now,
                "transitions": event.transitions + (Transition(status=status, at=now, reason=reason),),
            }
        )

    def observe(self, snapshot: FeatureSnapshot, trigger):
        now, v = snapshot.decision_time, snapshot.values
        mid, spread, depth = (v[x].value for x in ("midprice", "spread", "depth"))
        valid = all(v[x].quality == Quality.GOOD for x in ("midprice", "spread", "depth"))
        for i, event in enumerate(self.events):
            if event.status in TERMINAL:
                continue
            if (
                snapshot.session_id != event.session_id
                or getattr(trigger, "phase", "CONTINUOUS") != "CONTINUOUS"
            ):
                self.events[i] = self.transition(event, S.CENSORED, now, "session boundary")
                continue
            elapsed = (now - event.transitions[0].at).total_seconds()
            if elapsed > self.timeout:
                self.events[i] = self.transition(event, S.CENSORED, now, "incomplete markout/recovery window")
                continue
            if not valid:
                if v["quote_age"].value is not None and v["quote_age"].value > 15:
                    self.events[i] = self.transition(event, S.CENSORED, now, "quote gap exceeded 15 seconds")
                continue
            if event.status == S.DETECTED:
                event = self.transition(event, S.ACTIVE, now, "subsequent available observation")
            elif event.status == S.ACTIVE and elapsed >= 2:
                event = self.transition(event, S.MARKOUT_PENDING, now, "awaiting observation horizon")
            # A carried-forward pre-horizon quote must never be a future markout.
            is_quote = trigger.kind == "quote" and trigger.event_time > event.event_time
            updates = {}
            if is_quote:
                impact = event.direction * (mid - event.baseline_mid)
                if event.initial_impact is None:
                    updates["initial_impact"] = impact
                if spread <= event.baseline_spread and event.spread_recovery_seconds is None:
                    updates["spread_recovery_seconds"] = elapsed
                if depth >= event.baseline_depth and event.depth_recovery_seconds is None:
                    updates["depth_recovery_seconds"] = elapsed
                if (
                    now >= event.horizon_at
                    and trigger.event_time >= event.horizon_at
                    and event.markout is None
                ):
                    initial = updates.get("initial_impact", event.initial_impact)
                    updates.update(
                        markout=impact,
                        markout_observed_at=now,
                        markout_source_time=trigger.event_time,
                        impact_retention=impact / initial if initial else None,
                    )
            if updates:
                updates.update(
                    processed_at=now,
                    available_at=now,
                    observation_refs=event.observation_refs + (trigger.event_id,),
                )
            event = event.model_copy(update=updates)
            if event.markout is not None and event.status == S.MARKOUT_PENDING:
                event = self.transition(event, S.OBSERVING_RECOVERY, now, "post-horizon quote observed")
            elif (
                event.status == S.OBSERVING_RECOVERY
                and event.spread_recovery_seconds is not None
                and event.depth_recovery_seconds is not None
            ):
                event = self.transition(event, S.MATURED, now, "markout and recovery observed")
            self.events[i] = event
        if isinstance(trigger, MarketTrade) and trigger.quantity >= self.threshold:
            direction = 1 if trigger.side == "BUY" else -1 if trigger.side == "SELL" else None
            status = S.DETECTED if valid and trigger.side != "UNKNOWN" else S.INVALID
            reason = (
                "mock flow-size threshold; inferred direction"
                if status == S.DETECTED
                else "missing fresh baseline or direction"
            )
            self.events.append(
                ShockEvent(
                    event_id=f"shock:{trigger.event_id}",
                    source=trigger.source,
                    event_time=trigger.event_time,
                    received_at=trigger.received_at,
                    processed_at=now,
                    available_at=now,
                    raw_ref=trigger.raw_ref,
                    symbol=trigger.symbol,
                    session_id=trigger.session_id,
                    status=status,
                    direction=direction,
                    quantity=trigger.quantity,
                    baseline_mid=mid,
                    baseline_spread=spread,
                    baseline_depth=depth,
                    observation_refs=(*snapshot.values["midprice"].dependencies, trigger.event_id),
                    horizon_at=now + timedelta(seconds=self.horizon),
                    transitions=(Transition(status=status, at=now, reason=reason),),
                )
            )
        # Bounded dashboard state; journal preserves every revision.
        if len(self.events) > 256:
            self.events = self.events[-256:]
