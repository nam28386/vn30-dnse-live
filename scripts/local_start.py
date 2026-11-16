"""Khởi động đồng thời backend và frontend trên loopback; Ctrl+C để dừng."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def port_free(port):
    with socket.socket() as sock:
        try:
            # Match the platform's server bind behavior: old TIME_WAIT connections
            # must not be mistaken for an active listener.
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def clean_frontend_env(environ):
    """Browser tooling does not need backend credentials or proxy secrets."""
    blocked = ("SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "API_KEY")
    return {
        key: value
        for key, value in environ.items()
        if not key.upper().startswith(("DNSE_", "VITE_"))
        and not any(part in key.upper() for part in blocked)
        and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "DEBUG"}
    }


def get_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.load(response)


def wait_for(check, processes, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("Một tiến trình đã dừng; xem thông báo ngay phía trên.")
        try:
            if check():
                return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Hết thời gian khởi động; chạy doctor_local để kiểm tra.")


def stop(processes):
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("MOCK", "LIVE"), required=True)
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("Cần Python 3.11 trở lên.")
    if not (ROOT / "pyproject.toml").is_file() or not (ROOT / "frontend/package.json").is_file():
        raise RuntimeError("Không tìm thấy repository đầy đủ; hãy giải nén toàn bộ ZIP.")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("Cần Node.js 22+ và npm trong PATH.")
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, timeout=5, check=True
    ).stdout
    if int(version.strip().lstrip("v").split(".")[0]) < 22:
        raise RuntimeError("Cần Node.js 22 trở lên.")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise RuntimeError("Thiếu dependencies frontend; chạy npm --prefix frontend ci.")
    try:
        from vn30.api import app  # noqa: F401
    except Exception:
        raise RuntimeError("Không import được vn30.api; chạy uv sync --frozen và doctor_local.") from None
    if args.backend_port == args.frontend_port:
        raise RuntimeError("Backend và frontend phải dùng hai cổng khác nhau.")
    for port in (args.backend_port, args.frontend_port):
        if not 1 <= port <= 65535 or not port_free(port):
            raise RuntimeError(f"Cổng {port} không khả dụng; dừng tiến trình đang dùng cổng rồi thử lại.")
    backend_env = os.environ.copy()
    backend_env["VN30_MODE"] = args.mode
    frontend_env = clean_frontend_env(os.environ)
    frontend_env["VN30_BACKEND_URL"] = f"http://127.0.0.1:{args.backend_port}"
    check = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            'await Promise.all([import("vite"),import("react"),import("lightweight-charts")])',
        ],
        cwd=ROOT / "frontend",
        env=frontend_env,
        capture_output=True,
        timeout=20,
    )
    if check.returncode:
        raise RuntimeError("Dependencies frontend không đầy đủ; chạy npm --prefix frontend ci.")
    processes = []
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "vn30.api:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.backend_port),
                ],
                cwd=ROOT,
                env=backend_env,
            )
        )
        backend = f"http://127.0.0.1:{args.backend_port}"
        wait_for(lambda: get_json(backend + "/healthz") == {"status": "ok", "mode": args.mode}, processes)
        processes.append(
            subprocess.Popen(
                [node, str(vite), "--host", "127.0.0.1", "--port", str(args.frontend_port), "--strictPort"],
                cwd=ROOT / "frontend",
                env=frontend_env,
            )
        )
        frontend = f"http://127.0.0.1:{args.frontend_port}"
        wait_for(lambda: get_json(frontend + "/api/state").get("mode") == args.mode, processes)
        print(
            f"\nĐã khởi động ứng dụng; chế độ yêu cầu: {args.mode}. Mở {frontend}  (Ctrl+C để dừng).",
            flush=True,
        )
        if args.mode == "LIVE":
            health = get_json(backend + "/api/health")
            source = health.get("status")
            if source not in {"LIVE", "BLOCKED", "CONNECTED_NO_TRADES", "STALE", "DISCONNECTED"}:
                source = "UNKNOWN"
            print(
                f"Trạng thái nguồn: {source}. LIVE chỉ được xác nhận khi nhận dữ liệu DNSE hợp lệ.",
                flush=True,
            )
        while True:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("Một tiến trình đã dừng; xem thông báo ngay phía trên.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nĐang dừng các tiến trình do script khởi động.", flush=True)
    finally:
        stop(processes)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # All messages above are static or locally constructed; never include environment values.
        print(f"Không thể khởi động: {error}", file=sys.stderr)
        raise SystemExit(1)
