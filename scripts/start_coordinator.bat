@echo off
REM Run on the coordinator host from CMD. Edit config\nodes.json first.
REM Usage: scripts\start_coordinator.bat [port]   (default 8000; use 8080 if 8000 is taken)
cd /d "%~dp0.."
set PORT=%~1
if "%PORT%"=="" set PORT=8000
echo Coordinator listening on 0.0.0.0:%PORT%   (dashboard: http://127.0.0.1:%PORT%)
python -m uvicorn coordinator.main:app --host 0.0.0.0 --port %PORT%
