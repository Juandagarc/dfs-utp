# Run on Hosts B, C, D (Windows PowerShell).  .\scripts\start_node.ps1 -NodeId node1
param([Parameter(Mandatory=$true)][string]$NodeId, [int]$Port = 8001)
Set-Location (Join-Path $PSScriptRoot "..")
$env:NODE_ID = $NodeId
Write-Host "Storage node $NodeId on 0.0.0.0:$Port, files in .\storage\$NodeId"
python -m uvicorn node.main:app --host 0.0.0.0 --port $Port
