param([switch]$Network)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$localPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $localPython) {
    $python = $localPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = (Get-Command python).Source
} else {
    Write-Host "Hệ điều hành: $([Environment]::OSVersion.VersionString)"
    Write-Host "Project root: $ProjectRoot"
    Write-Host 'Python: MISSING'
    foreach ($tool in @('uv', 'node', 'npm')) {
        $command = Get-Command $tool -ErrorAction SilentlyContinue
        if ($command) {
            try { & $tool --version } catch { Write-Host "$tool : ERROR" }
        } else { Write-Host "$tool : MISSING" }
    }
    foreach ($name in @('DNSE_API_KEY', 'DNSE_API_SECRET')) {
        $present = if ([Environment]::GetEnvironmentVariable($name, 'Process')) { 'YES' } else { 'NO' }
        Write-Host "$name : $present"
    }
    Write-Host 'Import/API/frontend/WebSocket/DNSE: UNKNOWN (thiếu Python).'
    Write-Host 'Nguyên nhân: thiếu Python 3.11+; cài Python và uv, mở terminal mới, rồi chạy lại.'
    return
}
if ($Network) { & $python scripts/doctor_local.py --network }
else { & $python scripts/doctor_local.py }
