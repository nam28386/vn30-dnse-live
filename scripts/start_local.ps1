param([Parameter(Mandatory = $true)][ValidateSet('MOCK', 'LIVE')][string]$Mode)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'pyproject.toml'))) {
    throw 'Không tìm thấy pyproject.toml. Hãy giải nén đầy đủ ZIP và chạy script trong repository.'
}
foreach ($tool in @('uv', 'node', 'npm')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Thiếu $tool trong PATH. Cài Python 3.11+, uv và Node.js 22+ (gồm npm), sau đó mở terminal mới."
    }
}
& uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Không cài được dependencies backend; kiểm tra Python, mạng và uv.lock.' }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'frontend/node_modules/vite/bin/vite.js'))) {
    $npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { (Get-Command npm.cmd).Source } else { (Get-Command npm).Source }
    & $npmCommand --prefix frontend ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Không cài được dependencies frontend; kiểm tra npm và mạng.' }
}
if ($Mode -eq 'LIVE') {
    & uv run --frozen pytest -q backend/tests/test_connectivity.py backend/tests/test_secure_dnse.py backend/tests/test_live_local.py
    if ($LASTEXITCODE -ne 0) { throw 'Security tests thất bại; không khởi động LIVE.' }
}
& uv run --frozen python scripts/local_start.py --mode $Mode
if ($LASTEXITCODE -ne 0) { throw 'Không khởi động được. Đọc thông báo phía trên hoặc chạy .\scripts\doctor_local.ps1.' }
