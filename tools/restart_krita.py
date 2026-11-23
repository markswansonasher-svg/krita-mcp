"""Restart Krita so it loads the plugin fresh (discards unsaved changes in open documents!).
Use during development after copying changed plugin files into pykrita/krita_mcp.
    uv run --with "mcp>=1.2,<2" python tools/restart_krita.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402

try:
    server.call("execute_python", code="for d in Application.documents():\n    d.setModified(False)\n"
                                       "from PyQt5.QtCore import QTimer\n"
                                       "QTimer.singleShot(200, Application.action('file_quit').trigger)")
except Exception as e:
    print("quit:", e)
for _ in range(60):
    try:
        server.call("ping", timeout=2)
        time.sleep(1)
    except Exception:
        break
time.sleep(3)
print(server.launch_krita())
