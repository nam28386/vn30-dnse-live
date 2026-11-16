"""Tổng hợp metadata market-data an toàn; không ghi raw data hoặc credentials."""

from .adapters.secure_dnse import TransportError
from .live import positive, quantity, source_time

FIELDS = {
    "instruments": {"symbol", "marketId", "securityGroupId", "symbolType", "listedDate"},
    "security_definition": {"symbol", "boardId", "productGrpId", "securityStatus", "finalTradeDate"},
    "session": {"marketId", "boardId", "eventId", "tradingSessionId", "tscProdGrpId", "time"},
    "trades": {"symbol", "boardId", "matchPrice", "matchQtty", "time", "side"},
    "quotes": {"symbol", "boardId", "bid", "offer", "time", "totalBidQtty", "totalOfferQtty"},
    "ohlc": {"t", "o", "h", "l", "c", "v", "nextTime"},
}
ENDPOINTS = {
    "instruments": "/market/instruments",
    "security_definition": "/price/{symbol}/secdef",
    "session": "/market/trading-session",
    "ohlc": "/price/ohlc",
    "trades": "/price/{symbol}/trades",
    "quotes": "/price/{symbol}/quotes",
}


def summary(operation, payload):
    result = {"record_count": None, "fields": [], "schema": "UNKNOWN", "timestamp": None}
    if operation not in FIELDS:
        return result
    if operation == "ohlc":
        if not isinstance(payload, dict):
            result["schema"] = "INVALID"
            return result
        result["fields"] = sorted(FIELDS[operation].intersection(payload))
        timestamps = payload.get("t")
        if isinstance(timestamps, list):
            result["record_count"] = len(timestamps)
            result["schema"] = "STRUCTURE_OBSERVED"
            if timestamps:
                try:
                    result["timestamp"] = source_time(timestamps[-1]).isoformat()
                except (ValueError, TypeError, OverflowError, OSError):
                    result["schema"] = "INVALID_TIMESTAMP"
        return result
    if isinstance(payload, dict):
        rows = payload.get(
            {"instruments": "data", "trades": "trades", "quotes": "quotes"}.get(operation, "data")
        )
    else:
        rows = payload
    if not isinstance(rows, list):
        result["schema"] = "INVALID"
        return result
    result["record_count"] = len(rows)
    if not rows:
        result["schema"] = "EMPTY"
        return result
    sample = rows[0]
    if not isinstance(sample, dict):
        result["schema"] = "INVALID"
        return result
    result["fields"] = sorted(FIELDS[operation].intersection(sample))
    result["schema"] = "STRUCTURE_OBSERVED"
    timestamp = sample.get("time")
    if timestamp is not None:
        try:
            result["timestamp"] = source_time(timestamp).isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            result["schema"] = "INVALID_TIMESTAMP"
    return result


class ObservingREST:
    """Giữ lại duy nhất HTTP status và metadata không nhạy cảm trong bộ nhớ."""

    def __init__(self, client):
        self.client = client
        self.observations = []

    def get(self, operation, *, symbol=None, query=None):
        try:
            result = self.client.get(operation, symbol=symbol, query=query)
        except TransportError as error:
            self.observations.append(
                {
                    "endpoint": ENDPOINTS.get(operation, "UNKNOWN"),
                    "http_status": error.http_status,
                    "result": str(error),
                }
            )
            raise
        status = getattr(self.client, "last_http_status", None)
        self.observations.append(
            {
                "endpoint": ENDPOINTS.get(operation, "UNKNOWN"),
                "http_status": status if isinstance(status, int) and 100 <= status <= 599 else None,
                "result": "RESPONSE_RECEIVED",
                **summary(operation, result),
            }
        )
        return result


def stream_summary(payload, received):
    """Các trường cho phép đã xác thực; không chuyển tiếp frame thô."""
    kind = payload.get("T")
    names = {"te": "Trade Extra", "q": "Quotes", "mi": "VN30 Index"}
    if kind not in names:
        return None
    allowed = {
        "te": {"T", "symbol", "time", "matchPrice", "matchQtty"},
        "q": {"T", "symbol", "time", "bid", "offer"},
        "mi": {"T", "indexName", "transactTime", "valueIndexes"},
    }[kind]
    timestamp = source_time(payload.get("transactTime" if kind == "mi" else "time"))
    if timestamp > received:
        raise ValueError("future_timestamp")
    result = {
        "channel": names[kind],
        "symbol": "VN30" if kind == "mi" else payload.get("symbol"),
        "fields": sorted(allowed.intersection(payload)),
        "event_timestamp": timestamp.isoformat(),
        "receive_timestamp": received.isoformat(),
        "freshness_seconds": round(max(0, (received - timestamp).total_seconds()), 3),
    }
    if kind == "te":
        result["price"] = positive(payload.get("matchPrice"))
        result["volume"] = quantity(payload.get("matchQtty"))
    elif kind == "q":
        bids, asks = payload.get("bid"), payload.get("offer")
        if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
            raise ValueError("invalid_quote")
        result.update(
            bid_levels=len(bids),
            ask_levels=len(asks),
            best_bid=positive(bids[0].get("price")),
            best_ask=positive(asks[0].get("price")),
        )
    else:
        result["index_value"] = positive(payload.get("valueIndexes"))
    return result
