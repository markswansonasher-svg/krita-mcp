@echo off
rem Double-click to install Krita MCP (needs Python 3.10+ from python.org or the Microsoft Store).
where py >nul 2>nul && (py -3 "%~dp0install.py" %*) || (python "%~dp0install.py" %*)
pause
