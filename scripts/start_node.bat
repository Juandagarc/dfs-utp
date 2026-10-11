@echo off
REM Run on a node host from CMD.   Usage: scripts\start_node.bat node1
if "%~1"=="" (echo Usage: scripts\start_node.bat node1^|node2^|node3 & exit /b 1)
cd /d "%~dp0.."
set NODE_ID=%~1
set PORT=%~2
if "%PORT%"=="" set PORT=8001
echo Storage node %NODE_ID% on 0.0.0.0:%PORT%, files in .\storage\%NODE_ID%
python -m uvicorn node.main:app --host 0.0.0.0 --port %PORT%
