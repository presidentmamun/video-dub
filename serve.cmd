@echo off
rem Starts Video Dubbing on http://localhost:8000 (needs Python; offers to install it if missing).
cd /d "%~dp0"
python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul && (python server.py & pause & exit /b)
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul && (py -3 server.py & pause & exit /b)
echo Python is needed to run Video Dubbing on this computer.
choice /m "Install Python now with winget"
if errorlevel 2 exit /b
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo Python was installed. Close this window and open serve.cmd again.
pause
