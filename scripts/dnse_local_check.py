"""Kiểm tra Production read-only; không in credentials hoặc response thô."""

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from vn30.adapters.secure_dnse import (
    Credentials,
    SecureREST,
    SecureStream,
    TransportError,
    preflight_rest,
    preflight_ws,
)
from vn30.connectivity import credentials_status
from vn30.diagnostics import ObservingREST, stream_summary
from vn30.live import LiveService, find_front
from vn30.logging import redact


def update_auth(report, observations):
    # Chỉ kết luận từ endpoint market-data có yêu cầu chữ ký theo OpenAPI.
    for item in observations:
        if item["endpoint"] != "/market/instruments":
            continue
        if item["http_status"] in (401, 403):
            report["authentication"] = "FAIL"
        elif (
            item["http_status"] is not None
            and 200 <= item["http_status"] < 300
            and item.get("schema") in {"STRUCTURE_OBSERVED", "EMPTY"}
        ):
            report["authentication"] = "PASS"


async def main():
    report = {
        "network": {"rest": "UNKNOWN", "websocket": "UNKNOWN"},
        "binding": "MISSING",
        "authentication": "UNKNOWN",
        "contract": "UNKNOWN",
        "endpoints": [],
        "history": "UNKNOWN",
        "rest_market": "UNKNOWN",
        "websocket": "UNKNOWN",
        "market_stream": "UNKNOWN",
        "messages": [],
    }
    rest = None
    if credentials_status().reason == "missing_credentials":
        report["error"] = "missing_credentials"
        print(json.dumps(redact(report), ensure_ascii=False, indent=2))
        return 1
    report["binding"] = "PRESENT"
    try:
        await preflight_rest()
        report["network"]["rest"] = "PASS"
        credentials = Credentials.from_environment()
        rest = ObservingREST(SecureREST(credentials, authorized=True))
        contract = await asyncio.to_thread(
            find_front, rest, datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
        )
        update_auth(report, rest.observations)
        report["contract"] = contract[1]
        service = LiveService()
        service.contract, service.rest = contract, rest
        await asyncio.to_thread(service.check_history)
        report["history"] = service.checks
        report["rest_market"] = (
            "REST_LIVE_VERIFIED" if service.checks.get("ohlc") == "DATA_VALIDATED" else "UNKNOWN"
        )
    except TransportError as error:
        report["error"] = str(error)
        if rest:
            update_auth(report, rest.observations)
        else:
            report["network"]["rest"] = "FAIL"
    except (ValueError, TypeError, OverflowError):
        report["error"] = "invalid_data"
    except Exception:
        # Exception text can contain request headers or untrusted server data.
        report["error"] = "internal_error"
    finally:
        if rest:
            report["endpoints"] = rest.observations
    if report["contract"] != "UNKNOWN":
        try:
            await preflight_ws()
            report["network"]["websocket"] = "PASS"

            def mark_authenticated():
                report["websocket"] = "WS_AUTHENTICATED"

            async def observe_message(message, received):
                before = service.accepted
                await service.on_message(message, received)
                if service.accepted > before:
                    report["messages"].append(stream_summary(message, received))

            await SecureStream(credentials, authorized=True).sample(
                contract[1], contract[2], on_authenticated=mark_authenticated, on_message=observe_message
            )
        except TransportError as error:
            report["websocket_error"] = str(error)
            if report["network"]["websocket"] == "UNKNOWN":
                report["network"]["websocket"] = "FAIL"
        except (ValueError, TypeError, OverflowError, OSError):
            report["websocket_error"] = "invalid_data"
        except Exception:
            report["websocket_error"] = "internal_error"
        if report["messages"]:
            report["market_stream"] = (
                "MARKET_STREAM_VERIFIED"
                if any(m["freshness_seconds"] <= 15 for m in report["messages"])
                else "STALE_MARKET_MESSAGES"
            )
        elif report["websocket"] == "WS_AUTHENTICATED" and "websocket_error" not in report:
            report["market_stream"] = "NO_VALID_MARKET_MESSAGE"
    print(json.dumps(redact(report), ensure_ascii=False, indent=2))
    return 0 if report["authentication"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
