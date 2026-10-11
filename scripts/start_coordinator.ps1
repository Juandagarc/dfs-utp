# Run on Host A (Windows PowerShell). Edit config\nodes.json first.
param([int]$Port = 8000)
Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "Coordinator listening on 0.0.0.0:$Port"
python -m uvicorn coordinator.main:app --host 0.0.0.0 --port $Port
