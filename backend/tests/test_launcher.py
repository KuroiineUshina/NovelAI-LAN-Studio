from __future__ import annotations

import logging
import socket
import sys
from pathlib import Path

from backend.app.config import AppPaths
from backend.app.launcher import (
    ServerThread,
    configure_logging,
    port_available,
    preferred_desktop_url,
)


def test_port_available_rejects_an_existing_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert port_available("0.0.0.0", port) is False
    assert port_available("127.0.0.1", port) is True


def test_desktop_url_prefers_reachable_machine_address_over_loopback():
    assert preferred_desktop_url(
        {
            "lan": ["http://192.168.0.2:8787"],
            "tailscale": ["http://100.101.2.3:8787"],
        },
        8787,
    ) == "http://192.168.0.2:8787"
    assert preferred_desktop_url(
        {"lan": [], "tailscale": ["http://100.101.2.3:8787"]}, 8787
    ) == "http://100.101.2.3:8787"
    assert preferred_desktop_url({"lan": [], "tailscale": []}, 8787) == (
        "http://127.0.0.1:8787"
    )


def test_windowed_exe_logging_does_not_require_console(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("NOVELAI_STUDIO_DATA_DIR", str(tmp_path / "server-data"))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    paths = AppPaths(tmp_path / "logs-data")
    configure_logging(paths)
    server = ServerThread("127.0.0.1", 18787)

    assert server.server.config.log_config is None
    assert (paths.logs / "app.log").exists()
    assert all(
        not isinstance(handler, logging.StreamHandler)
        or isinstance(handler, logging.FileHandler)
        for handler in logging.getLogger().handlers
    )

    logging.shutdown()
    logging.getLogger().handlers.clear()
