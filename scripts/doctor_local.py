"""Chẩn đoán cục bộ; chỉ in trạng thái, không in credentials hay response body."""

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import platform
import queue
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def version(command):
    executable = shutil.which(command + ".cmd") or shutil.which(command)
    if not executable:
        return "MISSING"
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
        text = result.stdout.strip().splitlines()
        if result.returncode or not text or len(text[0]) > 80:
            return "ERROR"
        # Version output is expected to contain only a version, never arbitrary command text.
        return text[0] if all(c.isalnum() or c in ".-+_ ()" for c in text[0]) else "ERROR"
    except (OSError, subprocess.SubprocessError):
        return "ERROR"


def port_status(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return "ĐANG LẮNG NGHE" if sock.connect_ex(("127.0.0.1", port)) == 0 else "TRỐNG"


def request(url, expected_json=False):
    try:
        with LOCAL_OPENER.open(url, timeout=2) as response:
            if expected_json:
                data = json.load(response)
                return f"HTTP {response.status}", data if isinstance(data, dict) else None
            return f"HTTP {response.status}", None
    except (OSError, ValueError, urllib.error.URLError):
        return "KHÔNG KẾT NỐI", None


async def websocket_status():
    if importlib.util.find_spec("websockets") is None:
        return "THIẾU DEPENDENCY"
    import websockets

    try:
        async with websockets.connect(
            "ws://127.0.0.1:5173/api/stream", proxy=None, open_timeout=2, close_timeout=1
        ) as ws:
            value = json.loads(await asyncio.wait_for(ws.recv(), 3))
            return (
                "PASS"
                if isinstance(value, dict) and value.get("mode") in {"MOCK", "LIVE"}
                else "DỮ LIỆU KHÔNG HỢP LỆ"
            )
    except Exception:
        return "KHÔNG KẾT NỐI"


def dnse_network():
    """HEAD không xác thực; kế thừa proxy, CA và không xuất thông tin lỗi thô."""
    try:
        context = ssl.create_default_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            return "INVALID_TLS_CONFIG"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(), urllib.request.HTTPSHandler(context=context)
        )
        request = urllib.request.Request("https://openapi.dnse.com.vn/", method="HEAD")
        try:
            with opener.open(request, timeout=5) as response:
                return f"HTTPS HTTP {response.status}; chưa xác thực"
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            return f"HTTPS HTTP {code}; chưa xác thực"
    except urllib.error.URLError as error:
        if "tunnel connection failed: 403" in str(error.reason).lower():
            return "PROXY_CONNECT_403; chưa có TLS tới DNSE"
        return "KHÔNG KẾT NỐI ĐƯỢC; kiểm tra proxy/network/TLS"
    except (OSError, TimeoutError):
        return "KHÔNG KẾT NỐI ĐƯỢC; kiểm tra proxy/network/TLS"


def direct_dns(host):
    # DNS only: production traffic is never rerouted around the configured proxy.
    outcome = queue.Queue(maxsize=1)

    def resolve():
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            outcome.put(True)
        except OSError:
            outcome.put(False)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        return "PASS" if outcome.get(timeout=2) else "FAIL"
    except queue.Empty:
        return "TIMEOUT"


async def dnse_websocket():
    if importlib.util.find_spec("websockets") is None:
        return "THIẾU DEPENDENCY"
    import websockets

    logger = logging.getLogger("vn30.doctor.transport")
    logger.disabled = True
    try:
        context = ssl.create_default_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            return "INVALID_TLS_CONFIG"
        async with asyncio.timeout(7):
            async with websockets.connect(
                "wss://ws-openapi.dnse.com.vn/v1/stream?encoding=json",
                ssl=context,
                logger=logger,
                open_timeout=5,
                close_timeout=1,
                max_size=1024 * 1024,
            ) as ws:
                welcome = json.loads(await ws.recv())
                return (
                    "HANDSHAKE PASS; chưa xác thực"
                    if isinstance(welcome, dict) and (welcome.get("sid") or welcome.get("session_id"))
                    else "HANDSHAKE KHÔNG HỢP LỆ"
                )
    except Exception:
        return "KHÔNG KẾT NỐI ĐƯỢC; chưa xác thực"


def inspect(network=False):
    print(f"Hệ điều hành: {platform.system()} {platform.release()}")
    print(f"Project root: {ROOT}")
    python_version = platform.python_version()
    print(f"Python: {python_version}{' (CẦN 3.11+)' if sys.version_info < (3, 11) else ''}")
    print(f"uv: {version('uv')}")
    print(f"Node.js: {version('node')}")
    print(f"npm: {version('npm')}")
    print(f"pyproject.toml: {'PRESENT' if (ROOT / 'pyproject.toml').is_file() else 'MISSING'}")
    print(
        f"Vite dependencies: {'PRESENT' if (ROOT / 'frontend/node_modules/vite/bin/vite.js').is_file() else 'MISSING'}"
    )
    try:
        import vn30.api  # noqa: F401

        imported = "PASS"
    except Exception:
        imported = "FAIL (chạy uv sync --frozen; kiểm tra Python và tzdata)"
    print(f"Import vn30.api: {imported}")
    for port in (8000, 5173):
        print(f"Cổng {port}: {port_status(port)}")
    backend, health = request("http://127.0.0.1:8000/healthz", expected_json=True)
    if backend == "HTTP 200" and (
        not health or health.get("status") != "ok" or health.get("mode") not in {"MOCK", "LIVE"}
    ):
        backend = "HTTP 200 nhưng health không hợp lệ"
    print(f"Backend /healthz: {backend}")
    backend_mode = health.get("mode") if health and health.get("mode") in {"MOCK", "LIVE"} else "UNKNOWN"
    print(f"Chế độ backend: {backend_mode}")
    frontend, _ = request("http://127.0.0.1:5173/")
    print(f"Frontend HTTP: {frontend}")
    proxy, state = request("http://127.0.0.1:5173/api/state", expected_json=True)
    valid_proxy = proxy == "HTTP 200" and state and state.get("mode") in {"MOCK", "LIVE"}
    print(f"Vite → API: {'PASS' if valid_proxy else 'CHƯA SẴN SÀNG'}")
    print(f"WebSocket qua Vite: {asyncio.run(websocket_status())}")
    for name in ("DNSE_API_KEY", "DNSE_API_SECRET"):
        print(f"{name}: {'YES' if os.environ.get(name) else 'NO'}")
    print(
        f"Chế độ terminal: {os.environ.get('VN30_MODE', 'MOCK').upper() if os.environ.get('VN30_MODE', 'MOCK').upper() in {'MOCK', 'LIVE'} else 'INVALID_CONFIG'}"
    )
    if network:
        print(f"DNS REST trực tiếp: {direct_dns('openapi.dnse.com.vn')} (proxy có thể phân giải riêng)")
        print(f"DNS WSS trực tiếp: {direct_dns('ws-openapi.dnse.com.vn')} (proxy có thể phân giải riêng)")
        print(f"DNSE REST: {dnse_network()}")
        print(f"DNSE WebSocket: {asyncio.run(dnse_websocket())}")
    else:
        print("DNSE: CHƯA KIỂM TRA (thêm --network); không ảnh hưởng MOCK")
    if not (ROOT / "pyproject.toml").is_file():
        print("Nguyên nhân: ZIP chưa được giải nén đầy đủ.")
    elif imported != "PASS":
        print("Nguyên nhân: thiếu dependencies backend hoặc cơ sở dữ liệu múi giờ.")
    elif not (ROOT / "frontend/node_modules/vite/bin/vite.js").is_file():
        print("Nguyên nhân: thiếu dependencies frontend.")
    elif backend != "HTTP 200" and port_status(8000) == "ĐANG LẮNG NGHE":
        print("Nguyên nhân: cổng 8000 đang được dùng bởi dịch vụ khác hoặc backend lỗi.")
    elif frontend != "HTTP 200" and port_status(5173) == "ĐANG LẮNG NGHE":
        print("Nguyên nhân: cổng 5173 đang được dùng bởi dịch vụ khác hoặc frontend lỗi.")
    elif backend != "HTTP 200" or frontend != "HTTP 200":
        print("Nguyên nhân: một hoặc cả hai dịch vụ chưa chạy.")
    elif not valid_proxy:
        print("Nguyên nhân: Vite không chuyển được /api tới backend.")
    else:
        print("Local HTTP/proxy: PASS; LIVE cần xác minh DNSE riêng.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network", action="store_true", help="Kiểm tra HTTPS DNSE không xác thực qua proxy hiện hành"
    )
    inspect(parser.parse_args().network)
