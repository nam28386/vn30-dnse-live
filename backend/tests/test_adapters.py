import asyncio
from unittest.mock import AsyncMock, Mock

from vn30.adapters.dnse import DNSEReadOnlyREST, DNSEReadOnlyStream, RESTClient, StreamingClient
from vn30.adapters.mock import metadata
from vn30.contracts import InstrumentMetadata


def test_rest_exact_sdk_method_calls():
    c = Mock(spec=RESTClient)
    adapter = DNSEReadOnlyREST(c)
    adapter.instruments(market_id="TEST", security_group_id="TEST", page=2)
    c.get_instruments.assert_called_once_with(
        market_id="TEST", security_group_id="TEST", page=2, limit=100, dry_run=False
    )
    adapter.security_definition("DYNAMIC", "G1")
    c.get_security_definition.assert_called_once_with(symbol="DYNAMIC", board_id="G1", dry_run=False)
    adapter.ohlc_history("DYNAMIC", "TEST", "1", 100, 200)
    c.get_ohlc.assert_called_once_with(
        bar_type="TEST", query={"symbol": "DYNAMIC", "resolution": "1", "from": 100, "to": 200}, dry_run=False
    )
    for name, method in [("trade_history", "get_trades"), ("quote_history", "get_quotes")]:
        getattr(adapter, name)("DYNAMIC", "G1", 100, 200, "cursor")
        getattr(c, method).assert_called_once_with(
            symbol="DYNAMIC",
            board_id="G1",
            from_date=100,
            to_date=200,
            limit=100,
            order="ASC",
            next_page_token="cursor",
            dry_run=False,
        )
    adapter.trading_session("TEST", "G1")
    c.get_lastest_session.assert_called_once_with(tsc_prod_grp_id="TEST", board_id="G1", dry_run=False)
    assert not hasattr(adapter, "post_order")


def test_stream_uses_only_market_subscriptions():
    client = AsyncMock(spec=StreamingClient)
    instrument = InstrumentMetadata.model_validate(metadata()[0])
    callbacks = {name: Mock() for name in ["trade", "quote", "index", "estimated_index", "session"]}
    asyncio.run(DNSEReadOnlyStream(client).subscribe(instrument, "TEST", callbacks))
    client.subscribe_trade_extra.assert_awaited_once_with(
        [instrument.symbol], on_trade_extra=callbacks["trade"], encoding="json", board_id="MOCK"
    )
    client.subscribe_quotes.assert_awaited_once_with(
        [instrument.symbol], on_quote=callbacks["quote"], encoding="json", board_id="MOCK"
    )
    client.subscribe_market_index.assert_awaited_once_with(
        market_index="VN30", on_market_index=callbacks["index"], encoding="json"
    )
    client.subscribe_estimated_market_index.assert_awaited_once_with(
        estimated_market_index="VN30", on_estimated_market_index=callbacks["estimated_index"], encoding="json"
    )
    client.subscribe_session.assert_awaited_once_with(
        product_group_id="TEST", board_id="MOCK", on_session=callbacks["session"], encoding="json"
    )
    assert len(client.mock_calls) == 5
