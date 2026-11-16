import os
import runpy
import socket
import subprocess
import sys
from pathlib import Path

local_start = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/local_start.py"))
clean_frontend_env = local_start["clean_frontend_env"]
port_free = local_start["port_free"]


def test_frontend_process_does_not_inherit_credentials_or_proxy():
    env = {
        "PATH": "example",
        "DNSE_API_KEY": "key",
        "DNSE_API_SECRET": "secret",
        "VITE_DNSE_KEY": "unsafe",
        "HTTPS_PROXY": "proxy",
        "TRADING_TOKEN": "token",
        "DEBUG": "true",
    }
    assert clean_frontend_env(env) == {"PATH": "example"}


def test_port_check_rejects_an_occupied_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        assert not port_free(sock.getsockname()[1])


def test_app_import_works_without_system_timezone_database():
    env = dict(os.environ, PYTHONTZPATH="")
    result = subprocess.run(
        [sys.executable, "-c", "from vn30.api import app"], env=env, capture_output=True, timeout=15
    )
    assert result.returncode == 0


def test_doctor_never_displays_credentials(monkeypatch, capsys):
    doctor = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/doctor_local.py"))
    inspect = doctor["inspect"]
    helpers = inspect.__globals__

    async def no_ws():
        return "NOT_RUNNING"

    monkeypatch.setenv("DNSE_API_KEY", "SYNTHETIC_KEY_8675309")
    monkeypatch.setenv("DNSE_API_SECRET", "SYNTHETIC_SECRET_8675309")
    monkeypatch.setitem(helpers, "version", lambda _: "test-version")
    monkeypatch.setitem(helpers, "port_status", lambda _: "TRỐNG")
    monkeypatch.setitem(helpers, "request", lambda *args, **kwargs: ("KHÔNG KẾT NỐI", None))
    monkeypatch.setitem(helpers, "websocket_status", no_ws)
    inspect()
    output = capsys.readouterr().out
    assert "DNSE_API_KEY: YES" in output and "DNSE_API_SECRET: YES" in output
    assert "SYNTHETIC_KEY_8675309" not in output
    assert "SYNTHETIC_SECRET_8675309" not in output


def test_port_reusable_after_connection_close():
    if os.name == "nt":
        import pytest

        pytest.skip("TIME_WAIT reuse semantics differ on Windows")
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            accepted, _ = listener.accept()
            accepted.shutdown(socket.SHUT_RDWR)
            accepted.close()
            client.recv(1)
    assert port_free(port)


def test_mock_wrapper_runs_after_zip_extraction_without_executable_bit(tmp_path):
    if os.name == "nt":
        import pytest

        pytest.skip("thử wrapper bash trên POSIX")
    source = Path(__file__).resolve().parents[2] / "scripts/start_mock.sh"
    wrapper = tmp_path / "start_mock.sh"
    wrapper.write_text(source.read_text())
    target = tmp_path / "start_local.sh"
    target.write_text('#!/usr/bin/env bash\nprintf "%s" "$1"\n')
    target.chmod(0o644)
    result = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout == "MOCK"
