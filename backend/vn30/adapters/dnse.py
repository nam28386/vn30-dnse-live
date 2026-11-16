"""SDK-backed read-only facades. No SDK client is constructed in MOCK.

Verified against dnse-tech/openapi-sdk at aa55a5117de2534707bca6165b6738e1cc6fc6a4.
Raw SDK responses deliberately remain raw until live normalization is validated.
"""

from datetime import datetime
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from ..contracts import InstrumentMetadata


class RESTClient(Protocol):
    def get_instruments(
        self,
        symbol=None,
        market_id=None,
        security_group_id=None,
        index_name=None,
        limit=None,
        page=None,
        version=None,
        dry_run=False,
    ): ...
    def get_security_definition(self, symbol, board_id=None, dry_run=False): ...
    def get_ohlc(self, bar_type, query=None, dry_run=False): ...
    def get_trades(
        self,
        symbol,
        board_id=None,
        from_date=None,
        to_date=None,
        limit=None,
        order=None,
        next_page_token=None,
        dry_run=False,
    ): ...
    def get_quotes(
        self,
        symbol,
        board_id=None,
        from_date=None,
        to_date=None,
        limit=None,
        order=None,
        next_page_token=None,
        dry_run=False,
    ): ...
    def get_lastest_session(self, tsc_prod_grp_id=None, board_id=None, dry_run=False): ...


class DNSEReadOnlyREST:
    def __init__(self, client: RESTClient):
        # SDK REST performs unchecked hostname verification and can print keys.
        # Its own client (including subclasses) must never enter this facade.
        if any(cls.__module__.startswith("dnse.api") for cls in type(client).__mro__):
            raise RuntimeError(
                "Official DNSE REST client is blocked until its transport and logging are hardened"
            )
        self._client = client

    def instruments(self, *, market_id=None, security_group_id=None, page=1, limit=100):
        return self._client.get_instruments(
            market_id=market_id, security_group_id=security_group_id, page=page, limit=limit, dry_run=False
        )

    def security_definition(self, symbol, board_id):
        return self._client.get_security_definition(symbol=symbol, board_id=board_id, dry_run=False)

    def ohlc_history(self, symbol, bar_type, resolution, start: int, end: int):
        return self._client.get_ohlc(
            bar_type=bar_type,
            query={"symbol": symbol, "resolution": resolution, "from": start, "to": end},
            dry_run=False,
        )

    def trade_history(self, symbol, board_id, start, end, next_page_token=None):
        return self._client.get_trades(
            symbol=symbol,
            board_id=board_id,
            from_date=start,
            to_date=end,
            limit=100,
            order="ASC",
            next_page_token=next_page_token,
            dry_run=False,
        )

    def quote_history(self, symbol, board_id, start, end, next_page_token=None):
        return self._client.get_quotes(
            symbol=symbol,
            board_id=board_id,
            from_date=start,
            to_date=end,
            limit=100,
            order="ASC",
            next_page_token=next_page_token,
            dry_run=False,
        )

    def trading_session(self, product_group_id, board_id):
        # Official SDK spelling, intentionally preserved.
        return self._client.get_lastest_session(
            tsc_prod_grp_id=product_group_id, board_id=board_id, dry_run=False
        )


def discover_front_contract(instruments: list[InstrumentMetadata], now: datetime) -> InstrumentMetadata:
    """Nearest unexpired VN30 future known at `now`; no future-known roll schedule."""
    today = now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    candidates = [
        x
        for x in instruments
        if x.available_at <= now
        and x.event_time <= now
        and x.underlying == "VN30"
        and x.instrument_type == "FUTURE"
        and x.tradable
        and x.listed_on <= today
        and x.expiry is not None
        and x.expiry >= today
    ]
    if not candidates:
        raise LookupError("no eligible point-in-time VN30 futures metadata")
    return min(candidates, key=lambda x: (x.expiry, x.symbol))


class StreamingClient(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def subscribe_trade_extra(self, symbols, on_trade_extra=None, encoding="json", board_id=None): ...
    async def subscribe_quotes(self, symbols, on_quote=None, encoding="json", board_id=None): ...
    async def subscribe_market_index(self, market_index, on_market_index=None, encoding="json"): ...
    async def subscribe_estimated_market_index(
        self, estimated_market_index, on_estimated_market_index=None, encoding="json"
    ): ...
    async def subscribe_session(self, product_group_id, board_id="*", on_session=None, encoding="json"): ...


class DNSEReadOnlyStream:
    """Use SDK auto_reconnect + re-subscription; request fresh snapshots after gaps.

    Callbacks receive SDK-decoded models, NOT unmodified wire frames. A live wire journal
    requires a separately audited pre-decode hook before production use.
    """

    def __init__(self, client: StreamingClient):
        # The SDK logs session IDs and untrusted server text via its own handlers.
        if any(cls.__module__.startswith("dnse.websocket") for cls in type(client).__mro__):
            raise RuntimeError("Official DNSE WebSocket client is blocked until its logging is hardened")
        self._client = client

    async def subscribe(
        self,
        instrument: InstrumentMetadata,
        product_group_id: str,
        callbacks: dict[str, Callable[[Any], None]],
    ):
        required = {"trade", "quote", "index", "estimated_index", "session"}
        if required - callbacks.keys():
            raise ValueError("all market-data callbacks required")
        await self._client.subscribe_trade_extra(
            [instrument.symbol],
            on_trade_extra=callbacks["trade"],
            encoding="json",
            board_id=instrument.board_id,
        )
        await self._client.subscribe_quotes(
            [instrument.symbol], on_quote=callbacks["quote"], encoding="json", board_id=instrument.board_id
        )
        await self._client.subscribe_market_index(
            market_index="VN30", on_market_index=callbacks["index"], encoding="json"
        )
        await self._client.subscribe_estimated_market_index(
            estimated_market_index="VN30",
            on_estimated_market_index=callbacks["estimated_index"],
            encoding="json",
        )
        await self._client.subscribe_session(
            product_group_id=product_group_id,
            board_id=instrument.board_id,
            on_session=callbacks["session"],
            encoding="json",
        )
