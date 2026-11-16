"""Check documented DNSE hosts without authentication or market-data access."""

import argparse
import json

from vn30.connectivity import HOSTS, probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=tuple(HOSTS), default="sandbox")
    parser.add_argument("--service", choices=("rest", "websocket", "all"), default="all")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    services = ("rest", "websocket") if args.service == "all" else (args.service,)
    output = [probe(args.environment, service, args.timeout) for service in services]
    print(json.dumps(output, indent=2))
    # A transport check succeeds only if every requested TLS and HTTP probe succeeds.
    return 0 if all(x["tls"]["status"] == x["http"]["status"] == "PASS" for x in output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
