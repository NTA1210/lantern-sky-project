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
    threading.Timer(1.2, open_browser).start()
    uvicorn.run("backend.app:app", host=config.HOST, port=config.PORT, reload=False)
