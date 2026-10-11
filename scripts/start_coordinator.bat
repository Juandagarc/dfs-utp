@echo off
REM Run on the coordinator host from CMD. Edit config\nodes.json first.
cd /d "%~dp0.."
echo Coordinator listening on 0.0.0.0:8000
python -m uvicorn coordinator.main:app --host 0.0.0.0 --port 8000
