"""Local read-only DNSE observation. Market records remain in memory by default."""

import asyncio
import math
from collections import deque
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .adapters.secure_dnse import Credentials, SecureREST, TransportError, preflight, stream_market
from .connectivity import credentials_status
from .features import FEATURES

ICT = ZoneInfo("Asia/Ho_Chi_Minh")


def source_time(value):
    if isinstance(value, dict):
        seconds = value.get("Seconds", value.get("seconds"))
        nanos = value.get("Nanos", value.get("nanos", 0))
        if seconds is None or not 0 <= int(nanos) < 1_000_000_000:
            raise ValueError("invalid_timestamp")
        return datetime.fromtimestamp(int(seconds) + int(nanos) / 1_000_000_000, timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, timezone.utc)
    if isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (result if result.tzinfo else result.replace(tzinfo=ICT)).astimezone(timezone.utc)
    raise ValueError("missing_timestamp")


def definitions(payload):
    if isinstance(payload, dict):
        payload = payload.get("data")
    if not isinstance(payload, list):
        raise TransportError("invalid_security_definition")
    return [x for x in payload if isinstance(x, dict)]


def find_front(rest, today):
    records = []
    fetched = 0
    for page in range(1, 11):
        body = rest.get(
            "instruments", query={"marketId": "DVX", "securityGroupId": "FU", "limit": 100, "page": page}
        )
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise TransportError("invalid_instruments")
        rows = body["data"]
        records.extend(
            x
            for x in rows
            if isinstance(x, dict)
            and x.get("symbolType") == "VN30F1M"
            and x.get("marketId") == "DVX"
            and x.get("securityGroupId") == "FU"
        )
        total = body.get("total")
        fetched += len(rows)
        if isinstance(total, int):
            if fetched >= total:
                break
            if not rows:
                raise TransportError("invalid_instruments_pagination")
        elif len(rows) < 100:
            break
    else:
        raise TransportError("instrument_pagination_limit")
    eligible = []
    for row in records:
        symbol = row.get("symbol")
        if not isinstance(symbol, str):
            continue
        for item in definitions(rest.get("security_definition", symbol=symbol)):
            if item.get("symbol") != symbol or item.get("productGrpId") != "FIO":
                continue
            expiry = item.get("finalTradeDate")
            board = item.get("boardId")
            try:
                day = date.fromisoformat(str(expiry)[:10])
            except ValueError:
                continue
            if day >= today and isinstance(board, str) and item.get("securityStatus") == "NO_HALT":
                eligible.append((day, symbol, board, item))
    if not eligible:
        raise TransportError("front_contract_not_found")
    # Multiple boards are possible; G1 is the documented regular board.
    eligible.sort(key=lambda x: (x[0], x[1], x[2] != "G1", x[2]))
    return eligible[0]


def positive(value):
    if isinstance(value, bool):
        raise ValueError("invalid_price")
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise ValueError("invalid_price")
    return n


def quantity(value):
    if isinstance(value, bool):
        raise ValueError("invalid_quantity")
    n = int(value)
    if n < 0 or n != float(value):
        raise ValueError("invalid_quantity")
    return n


def levels(data, *, bids):
    if not isinstance(data, list) or not 0 < len(data) <= 100:
        raise ValueError("invalid_depth")
    rows = [(positive(row["price"]), quantity(row.get("qtty", row.get("quantity")))) for row in data]
    for first, second in zip(rows, rows[1:]):
        if (bids and first[0] <= second[0]) or (not bids and first[0] >= second[0]):
            raise ValueError("invalid_book_order")
    return rows


def valid_ohlc(payload, start, end):
    if not isinstance(payload, dict):
        return False
    arrays = [payload.get(name) for name in ("t", "o", "h", "l", "c", "v")]
    if any(not isinstance(a, list) for a in arrays) or not arrays[0] or len(arrays[0]) > 100:
        return False
    if any(len(a) != len(arrays[0]) for a in arrays):
        return False
    try:
        return (
            all(start <= int(t) <= end for t in arrays[0])
            and all(positive(v) > 0 for a in arrays[1:5] for v in a)
            and all(quantity(v) >= 0 for v in arrays[5])
        )
    except (ValueError, TypeError, OverflowError):
        return False


class LiveService:
    def __init__(self, *, preflight_fn=preflight, rest_factory=SecureREST, stream_fn=stream_market):
        self.preflight_fn, self.rest_factory, self.stream_fn = preflight_fn, rest_factory, stream_fn
        self.status = "BLOCKED"
        self.reason = "checking_network"
        self.contract = None
        self.connected = False
        self.epoch_has_trade = False
        self.trades = deque(maxlen=600)
        self.raw = deque(maxlen=600)
        self.bid = self.ask = self.index = None
        self.bid_depth_levels = self.ask_depth_levels = None
        self.last_trade_at = self.last_quote_at = self.last_index_at = None
        self.last_received_at = None
        self.last_source_at = None
        self.accepted = self.rejected = self.reconnects = 0
        self.checks = {}
        self.rest = None
        self.credentials = None

    async def start(self):
        try:
            # Presence only: do not construct a client or contact DNSE if bindings are absent.
            if credentials_status().reason == "missing_credentials":
                raise TransportError("missing_credentials")
            # Test TLS and the WSS handshake before the first authenticated request.
            await self.preflight_fn()
            self.credentials = Credentials.from_environment()
            self.rest = self.rest_factory(self.credentials, authorized=True)
            self.contract = await asyncio.to_thread(find_front, self.rest, datetime.now(ICT).date())
            self.reason = "connecting"
            self.status = "DISCONNECTED"
            await asyncio.to_thread(self.check_history)
            while True:
                try:
                    await self.stream_fn(
                        self.credentials, self.contract[1], self.contract[2], self.on_connect, self.on_message
                    )
                except TransportError as e:
                    self.reason = str(e)  # fixed internal category only
                self.connected = False
                self.status = "DISCONNECTED"
                self.reconnects += 1
                await asyncio.sleep(min(2 ** min(self.reconnects, 4), 15))
        except TransportError as exc:
            self.reason = str(exc)
            self.status = "BLOCKED"
        except (ValueError, TypeError, OverflowError):
            self.reason = "invalid_market_metadata"
            self.status = "BLOCKED"
        except Exception:
            # Never log untrusted exception text, request objects, or response bodies.
            self.reason = "internal_error"
            self.status = "BLOCKED"

    def check_history(self):
        _, symbol, board, _ = self.contract
        now = int(datetime.now(timezone.utc).timestamp())
        calls = [
            ("session", {"tscProdGrpId": "FIO", "boardId": board}, None),
            (
                "ohlc",
                {
                    "symbol": symbol,
                    "type": "DERIVATIVE",
                    "resolution": "1D",
                    "from": now - 14 * 86400,
                    "to": now,
                },
                None,
            ),
            (
                "trades",
                {"boardId": board, "from": now - 600, "to": now, "limit": 20, "order": "DESC"},
                symbol,
            ),
            (
                "quotes",
                {"boardId": board, "from": now - 600, "to": now, "limit": 20, "order": "DESC"},
                symbol,
            ),
        ]
        for op, query, item in calls:
            try:
                payload = self.rest.get(op, symbol=item, query=query)
                if not isinstance(payload, (dict, list)):
                    self.checks[op] = "INVALID"
                    continue
                self.checks[op] = "RESPONSE_RECEIVED"
                if op == "ohlc":
                    self.checks[op] = (
                        "DATA_VALIDATED"
                        if valid_ohlc(payload, query["from"], query["to"])
                        else "EMPTY_OR_INVALID"
                    )
                if op in {"trades", "quotes"} and isinstance(payload, dict):
                    token = payload.get("nextPageToken")
                    if token:
                        next_page = self.rest.get(op, symbol=item, query={**query, "nextPageToken": token})
                        self.checks[op] = "TWO_PAGES_RECEIVED" if isinstance(next_page, dict) else "INVALID"
            except TransportError as exc:
                self.checks[op] = str(exc)

    async def on_connect(self):
        self.epoch_has_trade = False
        self.connected = True
        self.status = "CONNECTED_NO_TRADES"
        self.reason = "authenticated_waiting_market_data"

    async def on_message(self, payload, received):
        try:
            kind = payload.get("T")
            body = payload
            if kind == "mi" and payload.get("indexName") != "VN30":
                return
            if kind in {"q", "te"} and payload.get("symbol") != self.contract[1]:
                return
            field = "transactTime" if kind == "mi" else "time"
            processed = datetime.now(timezone.utc)
            if received > processed:
                raise ValueError("invalid_receive_time")
            observed = source_time(body.get(field))
            if observed > received:
                raise ValueError("future_source_time")
            if kind == "te":
                if self.last_trade_at and observed < self.last_trade_at:
                    raise ValueError("out_of_order")
                price, size = positive(body.get("matchPrice")), quantity(body.get("matchQtty"))
                if size == 0:
                    raise ValueError("invalid_quantity")
                processed = datetime.now(timezone.utc)
                # SDK side is not exchange-confirmed: do not assign a sign.
                self.trades.append(
                    {
                        "time": observed.isoformat(),
                        "received_at": received.isoformat(),
                        "processed_at": processed.isoformat(),
                        "available_at": processed.isoformat(),
                        "price": price,
                        "quantity": size,
                        "side": "UNKNOWN",
                        **{name: None for name in FEATURES},
                    }
                )
                self.last_trade_at = observed
                self.epoch_has_trade = True
            elif kind == "q":
                if self.last_quote_at and observed < self.last_quote_at:
                    raise ValueError("out_of_order")
                bids = levels(body.get("bid"), bids=True)
                asks = levels(body.get("offer"), bids=False)
                bid, ask = bids[0][0], asks[0][0]
                if bid > ask:
                    raise ValueError("crossed_book")
                processed = datetime.now(timezone.utc)
                self.bid, self.ask = bid, ask
                self.bid_depth_levels, self.ask_depth_levels = len(bids), len(asks)
                self.last_quote_at = observed
            elif kind == "mi":
                if self.last_index_at and observed < self.last_index_at:
                    raise ValueError("out_of_order")
                index_value = positive(body.get("valueIndexes"))
                processed = datetime.now(timezone.utc)
                self.index = index_value
                self.last_index_at = observed
            else:
                return
            self.raw.append((payload.copy(), received, processed))  # bounded, in-memory only
            self.last_received_at, self.last_source_at = received, observed
            self.accepted += 1
            self.reason = "market_data_received"
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            self.rejected += 1
            self.reason = "invalid_market_message"

    @staticmethod
    def age(when, now):
        return max(0.0, (now - when).total_seconds()) if when else None

    def state(self):
        now = datetime.now(timezone.utc)
        qa, ia, ta = (self.age(t, now) for t in (self.last_quote_at, self.last_index_at, self.last_trade_at))
        age = self.age(self.last_source_at, now)
        if self.connected:
            if (age is not None and age > 15) or (qa is not None and qa > 15):
                status = "STALE"
            elif not self.epoch_has_trade:
                status = "CONNECTED_NO_TRADES"
            elif age is None or ta > 15:
                status = "STALE"
            else:
                status = "LIVE"
        else:
            status = self.status
        values = {
            name: {"value": None, "quality": "MISSING", "available_at": now.isoformat()} for name in FEATURES
        }
        if self.bid is not None and qa is not None and qa <= 15:
            values["spread"] = {
                "value": self.ask - self.bid,
                "quality": "GOOD",
                "available_at": now.isoformat(),
            }
        for name, value in [("quote_age", qa), ("index_age", ia)]:
            values[name] = {
                "value": value,
                "quality": "MISSING" if value is None else "STALE" if value > 15 else "GOOD",
                "available_at": now.isoformat(),
            }
        symbol = self.contract[1] if self.contract else "—"
        expiry = self.contract[0].isoformat() if self.contract else None
        return {
            "mode": "LIVE",
            "version": "0.1.0",
            "clock": "REAL",
            "instrument": {"symbol": symbol, "expiry": expiry},
            "snapshot": {"decision_time": now.isoformat(), "session_id": None, "values": values},
            "history": list(self.trades),
            "events": [],
            "health": {
                "connected": self.connected,
                "quality": "GOOD" if status == "LIVE" else "STALE",
                "status": status,
                "reason": self.reason,
                "quote_age_seconds": qa,
                "index_age_seconds": ia,
                "rejected_records": self.rejected,
                "reconnects": self.reconnects,
                "message": "DNSE Production; dữ liệu MBP; không xác nhận chiều chủ động",
            },
            "market": {
                "best_bid": self.bid if qa is not None and qa <= 15 else None,
                "best_ask": self.ask if qa is not None and qa <= 15 else None,
                "bid_depth_levels": self.bid_depth_levels if qa is not None and qa <= 15 else None,
                "ask_depth_levels": self.ask_depth_levels if qa is not None and qa <= 15 else None,
                "index": self.index if ia is not None and ia <= 15 else None,
                "last_source_at": self.last_source_at.isoformat() if self.last_source_at else None,
                "last_received_at": self.last_received_at.isoformat() if self.last_received_at else None,
                "trade_age_seconds": ta,
            },
            "checks": dict(self.checks),
        }

    def feed_quality(self):
        return self.state()["health"]
