from __future__ import annotations
import os, threading, webbrowser
import uvicorn

def open_browser():
    if os.environ.get('LANTERN_NO_BROWSER') != '1':
        webbrowser.open('http://127.0.0.1:8000/control')

if __name__ == '__main__':
    threading.Timer(1.2, open_browser).start()
    uvicorn.run('backend.app:app', host='0.0.0.0', port=int(os.environ.get('PORT','8000')), reload=False)
