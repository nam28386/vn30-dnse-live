"""Offline signature audit against an independently obtained official SDK checkout.

Usage: python scripts/check_sdk_contract.py /tmp/dnse-openapi-sdk
No SDK imports, credentials or network calls are performed.
"""

import ast
import sys
from pathlib import Path

root = Path(sys.argv[1])
facade = ast.parse(Path("backend/vn30/adapters/dnse.py").read_text())
count = 0
for protocol, file, client in [
    ("RESTClient", "python/dnse/api/client.py", "DNSEClient"),
    ("StreamingClient", "python/dnse/websocket/client.py", "TradingClient"),
]:
    actual = next(
        n
        for n in ast.parse((root / file).read_text()).body
        if isinstance(n, ast.ClassDef) and n.name == client
    )
    expected = next(n for n in facade.body if isinstance(n, ast.ClassDef) and n.name == protocol)
    for method in expected.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        match = next(
            n
            for n in actual.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method.name
        )
        assert [a.arg for a in method.args.args] == [a.arg for a in match.args.args], method.name
        assert [ast.dump(n) for n in method.args.defaults] == [ast.dump(n) for n in match.args.defaults], (
            method.name
        )
        count += 1
print(f"{count} official SDK method signatures verified (offline; no live connection).")
