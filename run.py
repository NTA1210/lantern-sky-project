from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn

from backend import config


def open_browser():
    if os.environ.get("LANTERN_NO_BROWSER") != "1":
        webbrowser.open(f"http://127.0.0.1:{config.PORT}/control")


if __name__ == "__main__":
    if os.environ.get("LANTERN_NO_BROWSER") != "1" and not os.environ.get("LANTERN_BROWSER_OPENED"):
        os.environ["LANTERN_BROWSER_OPENED"] = "1"
        threading.Timer(1.0, open_browser).start()

    reload_enabled = os.environ.get("LANTERN_RELOAD", "1") == "1"
    uvicorn.run(
        "backend.app:app",
        host=config.HOST,
        port=config.PORT,
        reload=reload_enabled,
        reload_dirs=["backend", "frontend"],
        reload_excludes=["runtime/*", "self_test_output/*", "*.png", "*.jpg", "*.json"],
        timeout_graceful_shutdown=1,
    )
